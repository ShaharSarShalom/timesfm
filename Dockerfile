# Shahar removd this 
#FROM osrf/ros:humble-desktop-full AS base
# Start with NVIDIA CUDA base image, pick your image from here: https://hub.docker.com/r/nvidia/cuda
FROM nvidia/cuda:12.6.3-cudnn-devel-ubuntu22.04 as Base
# FROM nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

ENV PARALELL_WORKERS="48"

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive

# Make port 80 available to the world outside this container
# In Linux, port 80 is typically used for HTTP (Hypertext Transfer Protocol) communication. It is the default port for serving web pages over the internet. 
EXPOSE 80

# Install packages and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git-all \
    wget \
    curl \ 
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

###################### python env - start ######################
ARG ENABLE_PYTHON_ENV=true
# ARG PYTHON_ENV_VER=
ARG PYTHON_ENV_VER=3.11

# Install Python 3.10 and pip \
# use the  python3.10-dev vs the python3.10 because it's needed by opencv compilation
# python${PYTHON_ENV_VER}-distutils
RUN apt-get update && \
    apt-get install -y python${PYTHON_ENV_VER}-dev python${PYTHON_ENV_VER}-distutils && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_ENV_VER} 1 && \
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && \
    python3 get-pip.py && \
    rm get-pip.py 
# Set the working directory in the container
# WORKDIR /colcon_ws
# Copy the current directory contents into the container at /app
# COPY . /app
# Install any needed packages specified in requirements.txt
# (Replace with your actual requirements file if you have one)

# Upgrade pip
RUN python3 -m pip install --upgrade pip

RUN pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126

# Verify the installation of torch, torchvision, and torchaudio
RUN python3 -c "import torch; print('torch version:', torch.__version__)"
RUN python3 -c "import torchvision; print('torchvision version:', torchvision.__version__)"
RUN python3 -c "import torchaudio; print('torchaudio version:', torchaudio.__version__)"