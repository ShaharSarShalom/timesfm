"""
Example usage of the TimesFM Finetuning Framework.
"""

from os import path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.multiprocessing as mp
import yfinance as yf
from finetuning_torch import FinetuningConfig, TimesFMFinetuner
from huggingface_hub import snapshot_download
from torch.utils.data import Dataset

from timesfm import TimesFm, TimesFmCheckpoint, TimesFmHparams
from timesfm.pytorch_patched_decoder import PatchedTimeSeriesDecoder
import os


class TimeSeriesDataset(Dataset):
    """Dataset for time series data compatible with TimesFM."""

    def __init__(self, series: np.ndarray, context_length: int, horizon_length: int):
        """
        Initialize dataset.

        Args:
            series: Time series data
            context_length: Number of past timesteps to use as input
            horizon_length: Number of future timesteps to predict
        """
        self.series = series
        self.context_length = context_length
        self.horizon_length = horizon_length
        self._prepare_samples()

    def _prepare_samples(self) -> None:
        """Prepare sliding window samples from the time series."""
        self.samples = []
        total_length = self.context_length + self.horizon_length

        for start_idx in range(0, len(self.series) - total_length + 1):
            end_idx = start_idx + self.context_length
            x_context = self.series[start_idx:end_idx]
            x_future = self.series[end_idx : end_idx + self.horizon_length]
            self.samples.append((x_context, x_future))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        x_context, x_future = self.samples[index]

        x_context = torch.tensor(x_context, dtype=torch.float32)
        x_future = torch.tensor(x_future, dtype=torch.float32)

        input_padding = torch.zeros_like(x_context)
        freq = torch.zeros(1, dtype=torch.long)

        return x_context, input_padding, freq, x_future


def prepare_datasets(
    series: np.ndarray, context_length: int, horizon_length: int, train_split: float = 0.8
) -> Tuple[Dataset, Dataset]:
    """
    Prepare training and validation datasets from time series data.

    Args:
        series: Input time series data
        context_length: Number of past timesteps to use
        horizon_length: Number of future timesteps to predict
        train_split: Fraction of data to use for training

    Returns:
        Tuple of (train_dataset, val_dataset)
    """
    train_size = int(len(series) * train_split)
    train_data = series[:train_size]
    val_data = series[train_size:]

    # Create datasets
    train_dataset = TimeSeriesDataset(train_data, context_length=context_length, horizon_length=horizon_length)

    val_dataset = TimeSeriesDataset(val_data, context_length=context_length, horizon_length=horizon_length)

    return train_dataset, val_dataset


def get_model(load_weights: bool = False):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    repo_id = "google/timesfm-2.0-500m-pytorch"
    hparams = TimesFmHparams(
        backend=device,
        per_core_batch_size=32,
        horizon_len=128,
        num_layers=50,
        use_positional_embedding=False,
        context_len=192,
    )
    tfm = TimesFm(hparams=hparams, checkpoint=TimesFmCheckpoint(huggingface_repo_id=repo_id))

    model = PatchedTimeSeriesDecoder(tfm._model_config)
    if load_weights:
        checkpoint_path = path.join(snapshot_download(repo_id), "torch_model.ckpt")
        loaded_checkpoint = torch.load(checkpoint_path, weights_only=True)
        model.load_state_dict(loaded_checkpoint)
    model = model.to(device)
    return model, hparams, tfm._model_config


def plot_predictions(
    model: TimesFm,
    val_dataset: Dataset,
    save_path: Optional[str] = "predictions.png",
) -> None:
    """
    Plot model predictions against ground truth for a batch of validation data.

    Args:
        model: Trained TimesFM model
        val_dataset: Validation dataset
        save_path: Path to save the plot
    """
    import matplotlib.pyplot as plt

    model.eval()

    x_context, x_padding, freq, x_future = val_dataset[0]
    x_context = x_context.unsqueeze(0)  # Add batch dimension
    x_padding = x_padding.unsqueeze(0)
    freq = freq.unsqueeze(0)
    x_future = x_future.unsqueeze(0)

    device = next(model.parameters()).device
    x_context = x_context.to(device)
    x_padding = x_padding.to(device)
    freq = freq.to(device)
    x_future = x_future.to(device)

    with torch.no_grad():
        predictions = model(x_context, x_padding.float(), freq)
        predictions_mean = predictions[..., 0]  # [B, N, horizon_len]
        last_patch_pred = predictions_mean[:, -1, :]  # [B, horizon_len]

    context_vals = x_context[0].cpu().numpy()
    future_vals = x_future[0].cpu().numpy()
    pred_vals = last_patch_pred[0].cpu().numpy()

    context_len = len(context_vals)
    horizon_len = len(future_vals)

    plt.figure(figsize=(12, 6))

    plt.plot(range(context_len), context_vals, label="Historical Data", color="blue", linewidth=2)

    plt.plot(
        range(context_len, context_len + horizon_len),
        future_vals,
        label="Ground Truth",
        color="green",
        linestyle="--",
        linewidth=2,
    )

    plt.plot(range(context_len, context_len + horizon_len), pred_vals, label="Prediction", color="red", linewidth=2)

    plt.xlabel("Time Step")
    plt.ylabel("Value")
    plt.title("TimesFM Predictions vs Ground Truth")
    plt.legend()
    plt.grid(True)

    if save_path:
        plt.savefig(save_path)
        print(f"Plot saved to {save_path}")

    plt.close()


def get_data(context_len: int, horizon_len: int) -> Tuple[Dataset, Dataset]:
    df = yf.download("AAPL", start="2010-01-01", end="2019-01-01")
    time_series = df["Close"].values

    train_dataset, val_dataset = prepare_datasets(
        series=time_series,
        context_length=context_len,
        horizon_length=horizon_len,
        train_split=0.8,
    )

    print(f"Created datasets:")
    print(f"- Training samples: {len(train_dataset)}")
    print(f"- Validation samples: {len(val_dataset)}")
    return train_dataset, val_dataset


def single_gpu_example():
    """Basic example of finetuning TimesFM on stock data."""
    model, hparams, tfm_config = get_model(load_weights=True)
    config = FinetuningConfig(batch_size=256, num_epochs=5, learning_rate=1e-4, use_wandb=True)

    train_dataset, val_dataset = get_data(128, tfm_config.horizon_len)
    finetuner = TimesFMFinetuner(model, config)

    print("\nStarting finetuning...")
    results = finetuner.finetune(train_dataset=train_dataset, val_dataset=val_dataset)

    print("\nFinetuning completed!")
    print(f"Training history: {len(results['history']['train_loss'])} epochs")

    plot_predictions(
        model=model,
        val_dataset=val_dataset,
        save_path="timesfm_predictions.png",
    )


def setup_process(rank, world_size, model, config, train_dataset, val_dataset, return_dict):
    """Initialize the distributed process."""
    # Set up the process group
    os.environ["MASTER_ADDR"] = "localhost"
    os.environ["MASTER_PORT"] = "12355"

    # Initialize the process group
    torch.distributed.init_process_group(backend="nccl", init_method="env://", world_size=world_size, rank=rank)

    # Set the device for this process
    torch.cuda.set_device(rank)

    try:
        finetuner = TimesFMFinetuner(model, config, rank=rank)
        results = finetuner.finetune(train_dataset=train_dataset, val_dataset=val_dataset)

        if rank == 0:  # Only store results and plot from the main process
            return_dict["results"] = results
            plot_predictions(
                model=model,
                val_dataset=val_dataset,
                save_path="timesfm_predictions.png",
            )
    finally:
        # Cleanup - important!
        torch.distributed.destroy_process_group()


def multi_gpu_example():
    """Example of finetuning TimesFM using multiple GPUs."""
    # Define which GPUs to use
    gpu_ids = [0]  # Just using one GPU
    world_size = len(gpu_ids)

    # Initialize model and config
    model, hparams, tfm_config = get_model(load_weights=True)
    config = FinetuningConfig(
        batch_size=256,
        num_epochs=5,
        learning_rate=1e-4,
        use_wandb=False,
        distributed=True,
        gpu_ids=gpu_ids,
    )

    # Get datasets
    train_dataset, val_dataset = get_data(128, tfm_config.horizon_len)

    # Create a multiprocessing manager to share results between processes
    manager = mp.Manager()
    return_dict = manager.dict()

    # Launch processes
    mp.spawn(
        setup_process,
        args=(world_size, model, config, train_dataset, val_dataset, return_dict),
        nprocs=world_size,
        join=True,
    )

    # Get results from the main process
    results = return_dict.get("results", None)
    print("\nFinetuning completed!")
    if results:
        print(f"Training history: {len(results['history']['train_loss'])} epochs")

    return results


if __name__ == "__main__":
    # Use either single GPU or multi-GPU example
    # basic_example()  # Single GPU
    multi_gpu_example()  # Multi-GPU
