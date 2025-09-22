# artorize-processor-core
image processor for the artorize project

## Working Directory
- Always apply changes from the checked-out tree at `D:\projects\artorize-processor-core`.
- Avoid modifying sibling clones such as `C:\Users\neil_\PycharmProjects\artscraper` when following these docs; those paths refer to legacy projects.

## Local Test Shortcut
Use the project root on your `PYTHONPATH` so `pytest` resolves the in-repo packages:

```powershell
$env:PYTHONPATH='.'
pytest -q
Remove-Item Env:PYTHONPATH
```
