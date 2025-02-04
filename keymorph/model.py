import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from skimage import morphology


class KeyMorph(nn.Module):
    def __init__(
        self,
        keypoint_extractor,
        keypoint_aligner,
        num_keypoints,
        dim,
        max_train_keypoints=256,
        use_amp=False,
    ):
        """Forward pass for one mini-batch step.

        :param keypoint_extractor: Keypoint extractor network
        :param kp_aligner: Affine or TPS keypoint alignment module
        :param num_keypoitns: Number of keypoints
        :param dim: Dimension
        :param max_train_keypoints: Maximum number of keypoints to use during training
        """
        super(KeyMorph, self).__init__()
        self.keypoint_extractor = keypoint_extractor
        self.keypoint_aligner = keypoint_aligner
        self.num_keypoints = num_keypoints
        self.dim = dim
        self.max_train_keypoints = max_train_keypoints
        self.use_amp = use_amp

    def forward(self, img_f, img_m, tps_lmbda, return_aligned_points=False):
        """Forward pass for one mini-batch step.

        :param img_f, img_m: Fixed and moving images
        :param tps_lmbda: Lambda value for TPS
        """
        with torch.amp.autocast(
            device_type="cuda", enabled=self.use_amp, dtype=torch.float16
        ):
            # Extract keypoints
            points_f, points_m = self.extract_keypoints_step(img_f, img_m)
            points_f = points_f.view(-1, self.num_keypoints, self.dim)
            points_m = points_m.view(-1, self.num_keypoints, self.dim)

            if self.training and self.num_keypoints > self.max_train_keypoints:
                # Take mini-batch of keypoints
                key_batch_idx = np.random.choice(
                    self.num_keypoints, size=256, replace=False
                )
                points_f = points_f[:, key_batch_idx]
                points_m = points_m[:, key_batch_idx]

        # Align via keypoints
        grid = self.keypoint_aligner.grid_from_points(
            points_m, points_f, img_f.shape, lmbda=tps_lmbda
        )
        if return_aligned_points:
            points_a = self.keypoint_aligner.points_from_points(
                points_m, points_f, points_m, lmbda=tps_lmbda
            )
            return grid, points_f, points_m, points_a
        return grid, points_f, points_m

    def extract_keypoints_step(self, img1, img2):
        return self.keypoint_extractor(img1), self.keypoint_extractor(img2)


class Simple_Unet(nn.Module):
    """
    Neural network for Brain Extractor

    Arguments
    ---------
    input_ch   : input channel to the network
    out_ch     : output dimension of the network
    use_in     : use instance norm
    enc_nf     : list of int for the encoder filter size
    dec_nf     : list of int for the decoder filter size
    Return
    ------
        model : torch model
    """

    def __init__(self, input_ch, out_ch, use_in, enc_nf, dec_nf):
        super(Simple_Unet, self).__init__()

        self.down = torch.nn.MaxPool3d(2, 2)

        self.block0 = simple_block(input_ch, enc_nf[0], use_in)
        self.block1 = simple_block(enc_nf[0], enc_nf[1], use_in)
        self.block2 = simple_block(enc_nf[1], enc_nf[2], use_in)
        self.block3 = simple_block(enc_nf[2], enc_nf[3], use_in)

        self.block4 = simple_block(enc_nf[3], dec_nf[0], use_in)

        self.block5 = simple_block(dec_nf[0] * 2, dec_nf[1], use_in)
        self.block6 = simple_block(dec_nf[1] * 2, dec_nf[2], use_in)
        self.block7 = simple_block(dec_nf[2] * 2, dec_nf[3], use_in)
        self.block8 = simple_block(dec_nf[3] * 2, out_ch, use_in)

        self.conv = nn.Conv3d(out_ch, out_ch, kernel_size=3, padding=1)

    def forward(self, x_in):
        # Model
        x0 = self.block0(x_in)
        x1 = self.block1(self.down(x0))
        x2 = self.block2(self.down(x1))
        x3 = self.block3(self.down(x2))

        x = self.block4(self.down(x3))
        x = F.interpolate(x, scale_factor=2, mode="trilinear", align_corners=False)

        x = torch.cat([x, x3], 1)
        x = self.block5(x)
        x = F.interpolate(x, scale_factor=2, mode="trilinear", align_corners=False)

        x = torch.cat([x, x2], 1)
        x = self.block6(x)
        x = F.interpolate(x, scale_factor=2, mode="trilinear", align_corners=False)

        x = torch.cat([x, x1], 1)
        x = self.block7(x)
        x = F.interpolate(x, scale_factor=2, mode="trilinear", align_corners=False)

        x = torch.cat([x, x0], 1)
        x = self.block8(x)

        out = self.conv(x)

        return out


class simple_block(nn.Module):
    def __init__(self, in_channels, out_channels, use_in):
        super(simple_block, self).__init__()

        self.use_in = use_in

        self.conv1 = nn.Conv3d(
            in_channels, out_channels, kernel_size=3, stride=1, padding=1
        )
        self.bn1 = nn.InstanceNorm3d(out_channels)

        self.activation = nn.ReLU(out_channels)

    def forward(self, x):
        out = self.conv1(x)
        if self.use_in:
            out = self.bn1(out)
        out = self.activation(out)
        return out


"""Helper function for brain extractor"""


def clean_mask(mask, threshold=0.2):
    """
    Remove small predicted segmentation. It finds the largest connected component.
    If there are other region/islands that is less than threshold percentage in size,
    remove those region.

    Arguments
    ---------
    mask         : numpy 3D binary mask for use for brain extraction
    threshold    : remove if not size(obj)/size(largest_component) > threshold

    Return
    ------
        new_mask : cleaned up mask with smaller regions removed
    """

    connected = morphology.label(mask)
    islands = np.unique(connected)[1:]

    islands_size = {}
    max_size = []
    for i in islands:
        size = (connected == i).sum()
        islands_size[i] = size
        max_size += [size]

    max_size = np.max(max_size)

    _island_size = islands_size.copy()
    for key in _island_size:
        if not islands_size[key] / max_size > threshold:
            islands_size.pop(key, None)

    new_mask = np.zeros_like(mask).astype("uint8")
    for key in islands_size:
        new_mask += (connected == key).astype("uint8")

    return new_mask
