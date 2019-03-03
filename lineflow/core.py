import os
import pickle
import linecache
import copy
import mmap
from pathlib import Path
from itertools import accumulate, islice
from bisect import bisect


class Dataset:
    def __init__(self, dataset):
        if isinstance(dataset, Dataset):
            self._dataset = dataset._dataset
        else:
            self._dataset = dataset

        self._length = None

    def __iter__(self):
        yield from self._dataset

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            return [self.get_example(i) for i in range(start, stop, step)]
        return self.get_example(index)

    def __len__(self):
        if self._length is None:
            self._length = self.get_length()
        return self._length

    def __add__(self, other):
        return ConcatDataset(self, other)

    def get_example(self, i):
        return self._dataset[i]

    def get_length(self):
        return len(self._dataset)

    def map(self, map_func):
        return MapDataset(self, map_func)

    def concat(self, *datasets):
        return ConcatDataset(self, *datasets)

    def all(self):
        return list(self)

    def take(self, n):
        return list(islice(self, n))

    def first(self):
        return next(iter(self))

    def save(self, filename):
        cache = list(self)
        with open(filename, 'wb') as f:
            pickle.dump(cache, f)
        return CacheDataset(self, cache)

    @staticmethod
    def load(filename):
        with open(filename, 'rb') as f:
            dataset = pickle.load(f)
        return Dataset(dataset)


class ConcatDataset(Dataset):
    def __init__(self, *datasets):
        assert all(isinstance(d, Dataset) for d in datasets)

        self._datasets = datasets
        self._lengths = list(accumulate(len(d) for d in datasets))
        self._length = self._lengths[-1]
        self._offsets = [0] + self._lengths[:-1]

    def __iter__(self):
        for d in self._datasets:
            yield from d

    def get_example(self, i):
        j = bisect(self._lengths, i)
        return self._datasets[j][i - self._offsets[j]]

    @property
    def _dataset(self):
        return self


class MapDataset(Dataset):
    def __init__(self, dataset, map_func):
        assert callable(map_func)

        if isinstance(dataset, MapDataset):
            map_func_list = copy.deepcopy(dataset._map_func_list)
            map_func_list.append(map_func)
        else:
            map_func_list = [map_func]

        self._map_func_list = map_func_list

        super().__init__(dataset)

    def __iter__(self):
        for x in self._dataset:
            for map_func in self._map_func_list:
                x = map_func(x)
            yield x

    def get_example(self, i):
        x = self._dataset[i]
        for map_func in self._map_func_list:
            x = map_func(x)
        return x


class CacheDataset(MapDataset):
    def __init__(self, dataset, cache):
        if isinstance(dataset, MapDataset):
            map_func_list = copy.deepcopy(dataset._map_func_list)
        else:
            map_func_list = []

        self._map_func_list = map_func_list
        self._cache = cache
        self._length = len(self._cache)

        super(MapDataset, self).__init__(dataset)

    def __iter__(self):
        yield from self._cache

    def get_example(self, i):
        return self._cache[i]


class SingleTextDataset(Dataset):
    def __init__(self, filepath, encoding='utf-8'):
        filepath = Path(filepath)
        assert filepath.is_file()

        self._filepath = filepath
        self._encoding = encoding
        self._length = None

    def __iter__(self):
        with self._filepath.open(encoding=self._encoding) as f:
            for line in f:
                yield line.rstrip(os.linesep)

    def get_example(self, i):
        return linecache.getline(
            str(self._filepath), i + 1).rstrip(os.linesep)

    def get_length(self):
        return self._count_lines(self._filepath)

    def _count_lines(self, filepath):
        count = 0
        with filepath.open(mode='r+', encoding=self._encoding) as f:
            mm = mmap.mmap(f.fileno(), 0)
            while mm.readline():
                count += 1
        return count

    @property
    def _dataset(self):
        return self


class TextDataset(SingleTextDataset):
    def __new__(cls, filepaths, encoding='utf-8'):
        if isinstance(filepaths, str):
            return SingleTextDataset(filepaths, encoding)
        return super().__new__(cls)

    def __init__(self, filepaths, encoding='utf-8'):
        filepaths = [Path(p) for p in filepaths]
        assert all(p.is_file() for p in filepaths)

        self._filepaths = filepaths
        self._encoding = encoding
        self._length = None

    def __iter__(self):
        fps = [p.open(encoding=self._encoding) for p in self._filepaths]
        for lines in zip(*fps):
            yield tuple(l.rstrip(os.linesep) for l in lines)

    def get_example(self, i):
        return tuple(linecache.getline(str(p), i + 1).rstrip(os.linesep)
                     for p in self._filepaths)

    def get_length(self):
        return self._count_lines(self._filepaths[0])
