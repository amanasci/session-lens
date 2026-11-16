"""Check distribution contents for missing assets or accidental private files."""
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile


def check(names, archive):
    for name in names:
        parts = PurePosixPath(name).parts
        assert not {'data', '.git', '.codex', '.aws', '.agents', '.venv', '__pycache__'}.intersection(parts), (archive, name)
        assert not any(part.startswith('.env') for part in parts), (archive, name)
        assert not any(suffix in name for suffix in ('.sqlite', '.pyc')), (archive, name)
        assert PurePosixPath(name).name not in {'auth.json', 'config.toml'}, (archive, name)
        if name.endswith('.jsonl'):
            assert parts[-3:] == ('session_lens', 'examples', 'demo.jsonl'), (archive, name)
    for asset in ('static/index.html', 'static/app.js', 'static/styles.css', 'examples/demo.jsonl'):
        assert any(n.endswith('session_lens/' + asset) for n in names), (archive, 'Missing ' + asset)
    print(f'{archive.name}: {len(names)} entries; assets present, no private data')


def main():
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist')
    wheels, sources = list(directory.glob('*.whl')), list(directory.glob('*.tar.gz'))
    assert wheels and sources, 'Expected both a wheel and a source archive'
    for path in wheels:
        with zipfile.ZipFile(path) as archive:
            check(archive.namelist(), path)
    for path in sources:
        with tarfile.open(path) as archive:
            check(archive.getnames(), path)


if __name__ == '__main__':
    main()
