# KeyMorph: Robust Multi-modal Registration via Keypoint Detection

End-to-end learning-based image registration framework that relies on automatically extracting corresponding keypoints. 

## TLDR in code
The crux of the code is in the `forward()` function in `keymorph/model.py`, which performs one forward pass through the entire KeyMorph pipeline.

Here's a pseudo-code version of the function:
```
def forward(img_f, img_m, seg_f, seg_m, network, optimizer, kp_aligner):
    '''Forward pass for one mini-batch step. 
    Variables with (_f, _m, _a) denotes (fixed, moving, aligned).
    
    Args:
        img_f, img_m: Fixed and moving intensity image (bs, 1, l, w, h)
        seg_f, seg_m: Fixed and moving one-hot segmentation map (bs, num_classes, l, w, h)
        network: Keypoint extractor network
        kp_aligner: Affine or TPS keypoint alignment module
    '''
    optimizer.zero_grad()

    # Extract keypoints
    points_f = network(img_f)
    points_m = network(img_m)

    # Align via keypoints
    grid = kp_aligner.grid_from_points(points_m, points_f, img_f.shape, lmbda=lmbda)
    img_a, seg_a = utils.align_moving_img(grid, img_m, seg_m)

    # Compute losses
    mse = MSELoss()(img_f, img_a)
    soft_dice = DiceLoss()(seg_a, seg_f)

    if unsupervised:
        loss = mse
    else:
        loss = soft_dice

    # Backward pass
    loss.backward()
    optimizer.step()
```
The `network` variable is a CNN with center-of-mass layer which extracts keypoints from the input images.
The `kp_aligner` variable is a keypoint alignment module. It has a function `grid_from_points()` which returns a flow-field grid encoding the transformation to perform on the moving image. The transformation can either be affine or nonlinear.

## Requirements
Install the packages with `pip install -r requirements.txt`.

You might need to install Pytorch separately, according to your GPU and CUDA version.
Install Pytorch [here](https://pytorch.org/get-started/locally/).

## Downloading Trained Weights
You can find all trained weights for most models used in this repository (KeyMorph training, pretraining, and brain extraction) under [Releases](https://github.com/alanqrwang/keymorph/releases) in this repository.
Download them and put them in the `./weights/` folder.

## Registering brain volumes
For convenience, we provide a script `register.py` which registers two brain volumes using our trained weights.
To register two volumes with our best-performing model:

```
python register.py \
    --moving ./example_data/images/IXI_001.nii.gz \
    --fixed ./example_data/images/IXI_002.nii.gz \
    --load_path ./weights/numkey512_tps0_dice.4760.h5 \
    --num_keypoints 512 \
    --moving_seg ./example_data/labels/IXI_001.nii.gz \
    --fixed_seg ./example_data/labels/IXI_002.nii.gz 
```

`--moving_seg` and `--fixed_seg` are optional. If provided, the script will compute the Dice score between the registered moving segmentation map and the fixed segmentation map. Otherwise, it will only compute MSE between the registered moving image and the fixed image.

Add the flag `--save_preds` to save outputs to disk. The default location is `./register_output/`.

For all inputs, ensure that pixel values are min-max normalized to the $[0,1]$ range and that the spatial dimensions are $(L, W, H) = (128, 128, 128)$.

## Training KeyMorph
Use `run.py` to train KeyMorph.

We use the weights from the pretraining step to initialize our model. 
Our pretraining weights are provided in [Releases](https://github.com/evanmy/keymorph/releases/tag/weights).

The `--num_keypoints <num_key>` flag specifies the number of keypoints to extract per image as `<num_key>`.
For all commands, optionally add the `--use_wandb` flag to log results to Weights & Biases.

This repository supports several variants of training KeyMorph.
Here's a overview of the variants:

### Supervised vs. unsupervised
Unsupervised only requires intensity images and minimizes MSE loss, while supervised assumes availability of corresponding segmentation maps for each image and minimizes soft Dice loss.

To specify unsupervised, set `--loss_fn mse`.
To specify supervised, set `--loss_fn dice`.


### Affine vs. TPS
Affine uses an affine transformation to align the corresponding keypoints.

TPS uses a (non-linear) thin-plate-spline interpolant to align the corresponding keypoints. A hyperparameter `--tps_lmbda` controls the degree of non-linearity for TPS. A value of 0 corresponds to exact keypoint alignment (resulting in a maximally nonlinear transformation while still minimizing bending energy), while higher values result in the transformation becoming more and more affine-like. In practice, we find a value of 10 is very similar to an affine transformation.

To specify affine, set `--kp_align_method affine`.
To specify tps, set `--kp_align_method tps` and the lmbda value `--tps_lmbda 0`.

### Example commands
**Affine, Unsupervised**

To train unsupervised KeyMorph with affine transformation and 128 keypoints, use `mse` as the loss function:

```
python run.py --num_keypoints 128 --kp_align_method affine --loss_fn mse \
                --data_dir ./data/centered_IXI/ \
                --load_path ./weights/numkey128_pretrain.2500.h5
```

For unsupervised KeyMorph, optionally add `--kpconsistency_coeff` to optimize keypoint consistency across modalities for same subject:

```
python run.py --num_keypoints 128 --kp_align_method affine --loss_fn mse --kpconsistency_coeff 10 \
                --data_dir ./data/centered_IXI/ \
                --load_path ./weights/numkey128_pretrain.2500.h5
```

**Affine, Supervised**

To train supervised KeyMorph, use `dice` as the loss function:

```
python run.py --num_keypoints 128 --kp_align_method affine --loss_fn dice --mix_modalities \
                --data_dir ./data/centered_IXI/ \
                --load_path ./weights/numkey128_pretrain.2500.h5
```

Note that the `--mix_modalities` flag allows fixed and moving images to be of different modalities during training. This should not be set for unsupervised training, which uses MSE as the loss function.

**Nonlinear thin-plate-spline (TPS)**

To train the TPS variant of KeyMorph which allows for nonlinear registrations, specify `tps` as the keypoint alignment method and specify the tps lambda value: 

```
python run.py --num_keypoints 128 --kp_align_method tps --tps_lmbda 0 --loss_fn dice \
                --data_dir ./data/centered_IXI/ \
                --load_path ./weights/numkey128_pretrain.2500.h5
```

The code also supports sampling lambda according to some distribution (`uniform`, `lognormal`, `loguniform`). For example, to sample from the `loguniform` distribution during training:

```
python run.py --num_keypoints 128 --kp_align_method tps --tps_lmbda loguniform --loss_fn dice \
                --data_dir ./data/centered_IXI/ \
                --load_path ./weights/numkey128_pretrain.2500.h5
```

Note that supervised/unsupervised variants can be run similarly to affine, as described above.

## Step-by-step guide for reproducing our results

### Dataset 
[A] Scripts in `./notebooks/[A] Download Data` will download the IXI data and perform some basic preprocessing

[B] Once the data is downloaded `./notebooks/[B] Brain extraction` can be used to extract remove non-brain tissue. 

[C] Once the brain has been extracted, we center the brain using `./notebooks/[C] Centering`. During training, we randomly introduce affine augmentation to the dataset. This ensure that the brain stays within the volume given the affine augmentation we introduce. It also helps during the pretraining step of our algorithm.

### Pretraining KeyMorph

This step helps with the convergence of our model. We pick 1 subject and random points within the brain of that subject. We then introduce affine transformation to the subject brain and same transformation to the keypoints. In other words, this is a self-supervised task in where the network learns to predict the keypoints on a brain under random affine transformation. We found that initializing our model with these weights helps with the training.

To pretrain, run:
 
```
python pretraining.py --num_keypoints 128 --data_dir ./data/centered_IXI/ 
```

### Training KeyMorph
Follow instructions for "Training KeyMorph" above, depending on the variant you want.

### Evaluating KeyMorph
To evaluate on the test set, simply add the `--eval` flag to any of the above commands. For example, for affine, unsupervised KeyMorph evaluation:

```
python run.py --kp_align_method affine --num_keypoints 128 --loss_fn mse --eval \
                --load_path ./weights/best_trained_model.h5
```

Evaluation proceeds by looping through all test augmentations in `list_of_test_augs`, all test modality pairs in `list_of_test_mods`, and all pairs of volumes in the test set.
Set `--save_preds` flag to save all outputs to disk.

**Automatic Delineation/Segmentation of the Brain**

For evaluation, we use [SynthSeg](https://github.com/BBillot/SynthSeg) to automatically segment different brain regions. Follow their repository for detailed intruction on how to use the model. 

## Issues
This repository is being actively maintained. Feel free to open an issue for any problems or questions.

## Legacy code
For a legacy version of the code, see our [legacy branch](https://github.com/alanqrwang/keymorph/tree/legacy).

## References
If this code is useful to you, please consider citing our papers.
The first conference paper contains the unsupervised, affine version of KeyMorph.
The second, follow-up journal paper contains the unsupervised/supervised, affine/TPS versions of KeyMorph.

Evan M. Yu, et al. "[KeyMorph: Robust Multi-modal Affine Registration via Unsupervised Keypoint Detection.](https://openreview.net/forum?id=OrNzjERFybh)" (MIDL 2021).

Alan Q. Wang, et al. "[A Robust and Interpretable Deep Learning Framework for Multi-modal Registration via Keypoints.](https://arxiv.org/abs/2304.09941)" (Medical Image Analysis 2023).
