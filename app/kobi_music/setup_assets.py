"""Install published model weights and the built-in GM SoundFont."""

from pathlib import Path
import os
import shutil
from subprocess import SubprocessError
from zipfile import BadZipFile

from copisteria.paths import MODELS
from huggingface_hub import snapshot_download
import torch

from . import kobi_bank
from .pipeline import BUILTIN, MICROSCOPIC
from .sound import BUILTIN_URL, check_font, download_font


def main():
    print('PyTorch', torch.__version__, 'CUDA', torch.cuda.is_available(), flush=True)
    for detector in ('28m', '2m'):
        snapshot_download(f'kobimusic/copista-{detector}', local_dir=MODELS, allow_patterns=['*.pt'])
    BUILTIN.parent.mkdir(parents=True, exist_ok=True)
    if not BUILTIN.is_file():
        local = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'MuseScore 3/sound' / BUILTIN.name
        if os.name == 'nt' and local.is_file():
            check_font(local)
            shutil.copyfile(local, BUILTIN)
        else:
            download_font(BUILTIN_URL, BUILTIN)
    check_font(BUILTIN)
    if not MICROSCOPIC.is_file():
        try:
            kobi_bank.download(MICROSCOPIC)
        except (OSError, ValueError, SubprocessError, BadZipFile) as exc:
            print(f'Optional Kobi Microscopic bank unavailable: {exc}', flush=True)


if __name__ == '__main__':
    main()
