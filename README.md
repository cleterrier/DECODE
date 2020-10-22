# DECODE
**Deep learning enables fast and dense single-molecule localization with high accuracy**

This is the *official* implementation of the preprint (Link to ArXiV).
[General Words about DECODE]
The easiest way to try out the algorithm is to have a look at the Google Colab Notebooks we provide for training our algorithm and fitting experimental data. For installation instructions and further information please **refer to our** [**docs**](https://decode.readthedocs.io). 
You can find these here:
- DECODE Training [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/18V1TLLu63CXSWihwoGX7ZQ5wj0Qk7GnD?usp=sharing)
- DECODE Fitting [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/1O0mjuOjaOl0wnLZ11Xo92IsWrgqtXL17?usp=sharing)
- [Documentation](https://decode.readthedocs.io)



## Local Installation
Please refer to our [docs](https://decode.readthedocs.io).

## Instructions for Developers
Travis CI: [![Build Status](https://travis-ci.com/Haydnspass/DeepSMLM.svg?token=qb4PpCab8Gb7CDLAuNTY&branch=master)](https://travis-ci.com/Haydnspass/DeepSMLM)

0. Clone the repository
1. Install conda environment from file and activate it. Use the respective environment depending on whether you have a CUDA GPU or not.
The cubic spline psf is pre-compiled in a different repo / as a separate package and will be installed automatically.

        # CUDA
        conda env create -f environment_cuda102_py38_pt15.yml
        conda activate decode_cuda_py38_pt15   

        # CPU / macOS
        conda env create -f environment_cpu_py38_pt15.yml
        conda activate deepsmlm_cpu

3. Test whether everything works as expected

            # assuming you are in the repo folder
            pytest decode/test

            # or if you fancy some nice figures, depending on your IDE
            # you might need to close popping up matplot figures
            pytest decode/test --plot  

4. The package can be used in python as

    ```import decode```

### Note
Simulation heavily relies on the Cubic Spline PSF Implementation (Li, Y. et al. Real-time 3D single-molecule localization using experimental point spread functions. Nature Methods 15, 367–369 (2018)).
It has been factored out in a seperate Repo to make life easier (see https://github.com/Haydnspass/SplinePSF). It'll be auto-installed.

### Building the Docs
For this we provide a conda environment for the sake of easy use. 
```bash
conda env create -f environment_docs.yaml  # once
conda activate decode_docs

cd docs
make html
```
The docs can be found in the build folder.
 

### Building and Deploying
Please follow the instructions as described here. Note that create the wheels only for Google Colab. 
All users should install via conda.
```bash
# optional, only once: create a new conda build environment
conda create --name build_clean conda-build anaconda bump2version -c conda-forge
conda activate build_clean

# bump version so that all versions get updated automatically, creates a git version tag automatically
bump2version [major/minor/patch/release/build]  # --verbose --dry_run to see the effect

# upload git tag
git push --tags

# build wheels
python setup.py bdist_wheel
# edit git release and upload the wheels

# conda release
cd conda
conda-build -c turagalab -c pytorch -c conda-forge decode

anaconda upload -u [your username] [path as provided at the end of the conda-build output]
```
After this you may test the build in a clean environment.