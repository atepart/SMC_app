@echo off
setlocal

if "%1"=="" (
    echo Usage: release.bat ^<tag^>
    exit /b 1
) else (
    set "Tag=%1"
)

(
  echo """Application version metadata."""
  echo.
  echo __all__ = ["__version__", "REPO_SLUG"]
  echo.
  echo __version__ = "%Tag%"
  echo REPO_SLUG = "atepart/SMC_app"
) > aocapp\application\version.py

git add aocapp\application\version.py
git commit -m "Release %Tag%"
git tag -a %Tag% -m "Version %Tag%"
git push origin --tags
git push

endlocal
