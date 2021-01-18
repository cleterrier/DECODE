import warnings

import torch
import pathlib
import tifffile
from typing import Union, Tuple, Callable, Iterable

from tqdm import tqdm


def load_tif(file: (str, pathlib.Path)) -> torch.Tensor:
    """
    Reads the tif(f) files. When a folder is specified, potentially multiple files are loaded.
    Which are stacked into a new first axis.
    Make sure that if you provide multiple files (i.e. a folder) sorting gives the correct order. Otherwise we can
    not guarantee anything.

    Args:
        file: path to the tiff / or folder

    Returns:
        torch.Tensor: frames

    """

    p = pathlib.Path(file)

    """If dir, load multiple files and stack them if more than one found"""
    if p.is_dir():

        file_list = sorted(p.glob('*.tif*'))  # load .tif or .tiff
        frames = []
        for f in tqdm(file_list, desc="Tiff loading"):
            frames.append(torch.from_numpy(tifffile.imread(str(f)).astype('float32')))

        if frames.__len__() >= 2:
            frames = torch.stack(frames, 0)
        else:
            frames = frames[0]

    else:
        im = tifffile.imread(str(p))
        frames = torch.from_numpy(im.astype('float32'))

    if frames.squeeze().ndim <= 2:
        warnings.warn(f"Frames seem to be of wrong dimension ({frames.size()}), "
                      f"or could only find a single frame.", ValueError)

    return frames


def get_tif_tag(file: Union[str, pathlib.Path], tag: Union[str, Iterable[str]]):

    # def deep_get(dictionary, *keys):
    #     """get value of a nested dict"""
    #     return reduce(lambda d, key: d.get(key, None) if isinstance(d, dict) else None, keys, dictionary)
    #
    # if not isinstance(tag, str):
    #     tag = [tag]
    #
    # with tifffile.TiffFile(file) as tif:
    #     tif_tags = {}
    #
    #     for tag in tif.pages[0].tags.values():
    #         name, value = tag.name, tag.value
    #         tif_tags[name] = value
    #
    # return deep_get(tif_tags, tag)
    raise NotImplementedError


class BatchFileLoader:

    def __init__(self, par_folder: Union[str, pathlib.Path],
                 file_suffix: str = '.tif',
                 file_loader: Union[None, Callable] = None,
                 exclude_pattern: Union[None, str] = None):
        """
        Iterates through parent folder and returns the loaded frames as well as the filename in their iterator

        Example:
            >>> batch_loader = BatchFileLoader('dummy_folder')
            >>> for frame, file in batch_loader:
            >>>     out = model.forward(frame)

        Args:
            par_folder: parent folder in which the files are
            file_suffix: suffix to search for
            exclude_pattern: specifies excluded patterns via regex string. If that pattern is found anywhere (!) in the
            files path, the file will be ingored.

        """

        self.par_folder = par_folder if isinstance(par_folder, pathlib.Path) else pathlib.Path(par_folder)
        if not self.par_folder.is_dir():
            raise FileExistsError(f"Path {str(self.par_folder)} is either not a directory or does not exist.")

        self.files = list(self.par_folder.rglob('*' + file_suffix))
        self.file_loader = file_loader if file_loader is not None else load_tif
        self._exclude_pattern = exclude_pattern if isinstance(exclude_pattern, (list, tuple)) else [exclude_pattern]

        self.remove_by_exclude()

        self._n = -1

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self):
        return self

    def __next__(self) -> Tuple[torch.Tensor, pathlib.Path]:
        """

        Returns:
            torch.Tensor: frames
            Path: path to file

        """
        if self._n >= len(self) - 1:
            raise StopIteration

        self._n += 1
        return self.file_loader(self.files[self._n]), self.files[self._n]

    def remove_by_exclude(self):
        """
        Removes the the files that match the exclude pattern

        """

        if self._exclude_pattern is None:
            return

        assert isinstance(self._exclude_pattern, (list, tuple))

        for e in self._exclude_pattern:
            excludes = set(self.par_folder.rglob(e))
            self.files = list(set(self.files) - excludes)
