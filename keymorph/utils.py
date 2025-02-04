import torch
import torch.nn.functional as F
import math
import numpy as np
from collections import defaultdict
import wandb
import os
import argparse


def align_img(grid, x):
    return F.grid_sample(
        x, grid=grid, mode="bilinear", padding_mode="border", align_corners=False
    )


def rescale_intensity(array, out_range=(0, 1), percentiles=(0, 100)):
    array = array.float()

    if percentiles != (0, 100):
        cutoff = np.percentile(array, percentiles)
        np.clip(array, *cutoff, out=array)  # type: ignore[call-overload]
    in_min = array.min()
    in_range = array.max() - in_min
    out_min = out_range[0]
    out_range = out_range[1] - out_range[0]

    array -= in_min
    array /= in_range
    array *= out_range
    array += out_min
    return array


def parse_test_metric(mod, aug):
    mod1, mod2 = mod.split("_")
    if "rot" in aug:
        if aug == "rot0":
            rot_aug = [0, 0, 0]
        elif aug == "rot45":
            rot_aug = np.random.choice([0, math.pi / 4], size=3)
        elif aug == "rot90":
            rot_aug = np.random.choice([0, math.pi / 2], size=3)
        elif aug == "rot135":
            rot_aug = np.random.choice([0, 3 * math.pi / 4], size=3)
        elif aug == "rot180":
            rot_aug = np.random.choice([0, math.pi], size=3)
        aug_param = [(0, 0, 0), (0, 0, 0), rot_aug, (0, 0, 0, 0, 0, 0)]
    else:
        raise NotImplementedError()

    return mod1, mod2, aug_param


def str_or_float(x):
    try:
        return float(x)
    except ValueError:
        return x


def aggregate_dicts(dicts):
    result = defaultdict(list)
    for d in dicts:
        for k, v in d.items():
            result[k].append(v)
    return {k: sum(v) / len(v) for k, v in result.items()}


def initialize_wandb(config):
    if config.wandb_api_key_path is not None:
        with open(config.wandb_api_key_path, "r") as f:
            os.environ["WANDB_API_KEY"] = f.read().strip()

    wandb.init(**config.wandb_kwargs, resume=config.resume)
    wandb.config.update(config)


# Taken from https://sumit-ghosh.com/articles/parsing-dictionary-key-value-pairs-kwargs-argparse-python/
class ParseKwargs(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, dict())
        for value in values:
            key, value_str = value.split("=")
            if value_str.replace("-", "").isnumeric():
                processed_val = int(value_str)
            elif value_str.replace("-", "").replace(".", "").isnumeric():
                processed_val = float(value_str)
            elif value_str in ["True", "true"]:
                processed_val = True
            elif value_str in ["False", "false"]:
                processed_val = False
            else:
                processed_val = value_str
            getattr(namespace, self.dest)[key] = processed_val


def sample_valid_coordinates(x, num_points, dim):
    """
    x: input img, (1,1,dim1,dim2) or (1,1,dim1,dim2,dim3)
    num_points: how many points within the brain
    dim: Dimension, either 2 or 3

    Returns:
      points: Normalized coordinates in [0, 1], (1, num_points, dim)
    """
    if dim == 2:
        coords = sample_valid_coordinates_2d(x, num_points)
    elif dim == 3:
        coords = sample_valid_coordinates_3d(x, num_points)
    else:
        raise NotImplementedError
    return coords


def sample_valid_coordinates_2d(x, num_points):
    eps = 0
    mask = x > eps
    indices = []
    for _ in range(num_points):
        hit = 0
        while hit == 0:
            sample = torch.zeros_like(x)
            dim1 = np.random.randint(0, x.size(2))
            dim2 = np.random.randint(0, x.size(3))
            sample[:, :, dim1, dim2] = 1
            hit = (sample * mask).sum()
            if hit == 1:
                indices.append([dim2 / x.size(3), dim1 / x.size(2)])

    return torch.tensor(indices).view(1, num_points, 2)


def sample_valid_coordinates_3d(x, num_points):
    eps = 1e-1
    mask = x > eps
    indices = []
    for _ in range(num_points):
        hit = 0
        while hit == 0:
            sample = torch.zeros_like(x)
            dim1 = np.random.randint(0, x.size(2))
            dim2 = np.random.randint(0, x.size(3))
            dim3 = np.random.randint(0, x.size(4))
            sample[:, :, dim1, dim2, dim3] = 1
            hit = (sample * mask).sum()
            if hit == 1:
                indices.append([dim3 / x.size(4), dim2 / x.size(3), dim1 / x.size(2)])

    return torch.tensor(indices).view(1, num_points, 3)


def summary(network):
    """Print model summary."""
    print("")
    print("Model Summary")
    print("---------------------------------------------------------------")
    for name, _ in network.named_parameters():
        print(name)
    print(
        "Total parameters:",
        sum(p.numel() for p in network.parameters() if p.requires_grad),
    )
    print("---------------------------------------------------------------")
    print("")
