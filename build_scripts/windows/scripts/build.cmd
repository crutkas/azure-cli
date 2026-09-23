@echo off
SetLocal EnableDelayedExpansion

REM Double colon :: should not be used in parentheses blocks, so we use REM.
REM See https://stackoverflow.com/a/12407934/2199657

echo Build a Windows package using local CLI sources. Requires curl.exe, PowerShell, and msbuild.exe for MSI or 7-Zip for ZIP.
echo.

set "PATH=%PATH%;%ProgramFiles%\Git\bin;%ProgramFiles%\Git\usr\bin;C:\Program Files (x86)\Git\bin;C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin"

if "%CLI_VERSION%"=="" (
    echo Please set the CLI_VERSION environment variable, e.g. 2.0.13
    goto ERROR
)
@REM ARCH can be x86, x64 or arm64
if "%ARCH%"=="" (
    set ARCH=x86
)
@REM TARGET can be msi or zip
if "%TARGET%"=="" (
    set TARGET=msi
)
if not "%TARGET%"=="msi" if not "%TARGET%"=="zip" (
    echo Please set TARGET to "msi" or "zip"
    goto ERROR
)

if "%ARCH%"=="x86" (
    set PYTHON_ARCH=win32
) else if "%ARCH%"=="x64" (
    set PYTHON_ARCH=amd64
) else if "%ARCH%"=="arm64" (
    set PYTHON_ARCH=arm64
    if /i not "%PROCESSOR_ARCHITECTURE%"=="ARM64" if /i not "%PROCESSOR_ARCHITEW6432%"=="ARM64" (
        echo ARM64 packaging requires a native Windows ARM64 host. Cross-packaging is not supported.
        goto ERROR
    )
) else (
    echo Please set ARCH to "x86", "x64" or "arm64"
    goto ERROR
)
set PYTHON_VERSION=3.14.7

set WIX_DOWNLOAD_URL="https://azurecliprod.blob.core.windows.net/msi/wix310-binaries-mirror.zip"
if "%ARCH%"=="arm64" set WIX_DOWNLOAD_URL="https://github.com/wixtoolset/wix3/releases/download/wix3141rtm/wix314-binaries.zip"
set PYTHON_DOWNLOAD_URL="https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-%PYTHON_ARCH%.zip"

REM https://pip.pypa.io/en/stable/installation/#get-pip-py
set GET_PIP_DOWNLOAD_URL="https://bootstrap.pypa.io/get-pip.py"
set PACKAGE_NAME=Microsoft Azure CLI
if "%ARCH%"=="arm64" set PACKAGE_NAME=Microsoft Azure CLI arm64

if "%~1"=="--check" (
    echo ARCH=%ARCH% TARGET=%TARGET% PYTHON_ARCH=%PYTHON_ARCH%
    echo Python: %PYTHON_DOWNLOAD_URL%
    echo WiX: %WIX_DOWNLOAD_URL%
    echo Artifact: %PACKAGE_NAME%.%TARGET%
    exit /b 0
)
where curl.exe >nul 2>&1
if errorlevel 1 (
    echo curl.exe is required on PATH.
    goto ERROR
)
if "%TARGET%"=="msi" (
    where msbuild.exe >nul 2>&1
    if errorlevel 1 (
        echo MSBuild is required on PATH to build MSI packages.
        goto ERROR
    )
) else (
    if not exist "%ProgramFiles%\7-Zip\7z.exe" (
        echo 7-Zip is required at "%ProgramFiles%\7-Zip\7z.exe" to build ZIP packages.
        goto ERROR
    )
)

REM Set up the output directory and temp. directories
echo Cleaning previous build artifacts...
set OUTPUT_DIR=%~dp0..\out
if exist %OUTPUT_DIR% rmdir /s /q %OUTPUT_DIR%
mkdir %OUTPUT_DIR%

set ARTIFACTS_DIR=%~dp0..\artifacts
mkdir %ARTIFACTS_DIR%
set PIP_CACHE_DIR=%ARTIFACTS_DIR%\pip-cache
set TEMP_SCRATCH_FOLDER=%ARTIFACTS_DIR%\cli_scratch
set BUILDING_DIR=%ARTIFACTS_DIR%\cli
set WIX_DIR=%ARTIFACTS_DIR%\wix
if "%ARCH%"=="arm64" set WIX_DIR=%ARTIFACTS_DIR%\wix-arm64-3.14.1
set PYTHON_DIR=%ARTIFACTS_DIR%\Python-%PYTHON_VERSION%-%ARCH%
if "%ARCH%"=="arm64" (
    set AZURE_CONFIG_DIR=%ARTIFACTS_DIR%\azure-config-arm64
    set AZURE_EXTENSION_DIR=%ARTIFACTS_DIR%\azure-extensions-arm64
)

REM Get the absolute directory since we pushd into different levels of subdirectories.
PUSHD %~dp0..\..\..
SET REPO_ROOT=%CD%
POPD

REM reset working folders
if exist %BUILDING_DIR% rmdir /s /q %BUILDING_DIR%
REM rmdir always returns 0, so check folder's existence
if exist %BUILDING_DIR% (
    echo Failed to delete %BUILDING_DIR%.
    goto ERROR
)
mkdir %BUILDING_DIR%

if exist %TEMP_SCRATCH_FOLDER% rmdir /s /q %TEMP_SCRATCH_FOLDER%
if exist %TEMP_SCRATCH_FOLDER% (
    echo Failed to delete %TEMP_SCRATCH_FOLDER%.
    goto ERROR
)
mkdir %TEMP_SCRATCH_FOLDER%

if exist %REPO_ROOT%\privates (
    copy %REPO_ROOT%\privates\*.whl %TEMP_SCRATCH_FOLDER%
)

if "%TARGET%" == "msi" (
    REM ensure wix is available
    if exist %WIX_DIR% (
        echo Using existing Wix at %WIX_DIR%
    )
    if not exist %WIX_DIR% (
        mkdir %WIX_DIR%
        pushd %WIX_DIR%
        echo Downloading Wix.
        curl --fail --location --output wix-archive.zip %WIX_DOWNLOAD_URL%
        if errorlevel 1 goto ERROR
        powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath wix-archive.zip -DestinationPath . -Force"
        if errorlevel 1 goto ERROR
        del wix-archive.zip
        echo Wix downloaded and extracted successfully.
        popd
    )
)

REM ensure Python is available
if exist %PYTHON_DIR% (
    echo Using existing Python at %PYTHON_DIR%
)
if not exist %PYTHON_DIR% (
    echo Setting up Python and pip
    mkdir %PYTHON_DIR%
    pushd %PYTHON_DIR%

    echo Downloading Python
    curl --fail --location --output python-archive.zip %PYTHON_DOWNLOAD_URL%
    if errorlevel 1 goto ERROR
    powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath python-archive.zip -DestinationPath . -Force"
    if errorlevel 1 goto ERROR
    del python-archive.zip
    echo Python downloaded and extracted successfully

    REM Append `import site` to python*._pth so site.py runs at startup
    REM (which adds Lib\site-packages to sys.path). We keep the file (rather
    REM than deleting it) because on Python 3.14+ removing it breaks pip's
    REM PEP 517 isolated BuildEnvironment subprocess: the child python.exe
    REM can no longer locate the stdlib zip and dies in init_fs_encoding
    REM with ModuleNotFoundError: No module named 'encodings'.
    REM Keeping an explicit _pth makes stdlib + site-packages discoverable
    REM in both the parent and any spawned subprocess.
    REM https://github.com/pypa/pip/issues/4207#issuecomment-297396913
    REM https://docs.python.org/3/using/windows.html#finding-modules
    if exist python*._pth (
        for %%f in (python*._pth) do (
            findstr /x "import site" "%%f" >nul || echo import site>> %%f
        )
    )

    echo Installing pip
    curl --fail --location --output get-pip.py %GET_PIP_DOWNLOAD_URL%
    if errorlevel 1 goto ERROR
    %PYTHON_DIR%\python.exe get-pip.py
    if errorlevel 1 goto ERROR
    del get-pip.py
    echo Pip set up successful

    REM setuptools is not installed by default in Python 3.12, but it is required by some dependencys
    REM See https://github.com/Azure/azure-cli/pull/27196
    REM Install wheel to force pip install azure-cli in legacy mode
    REM see https://github.com/Azure/azure-cli/pull/29887
    echo Installing setuptools wheel
    %PYTHON_DIR%\python.exe -Im pip install setuptools wheel
    if errorlevel 1 goto ERROR

    popd
)
set PYTHON_EXE=%PYTHON_DIR%\python.exe
%PYTHON_EXE% -I %REPO_ROOT%\build_scripts\windows\scripts\verify_runtime.py --root %PYTHON_DIR% --arch %ARCH%
if errorlevel 1 goto ERROR


robocopy %PYTHON_DIR% %BUILDING_DIR% /s /NFL /NDL
if errorlevel 8 goto ERROR

set CLI_SRC=%REPO_ROOT%\src
for %%a in (%CLI_SRC%\azure-cli %CLI_SRC%\azure-cli-core %CLI_SRC%\azure-cli-telemetry) do (
   pushd %%a
   %BUILDING_DIR%\python.exe -Im pip install --no-warn-script-location --no-cache-dir --no-deps .
   if errorlevel 1 goto ERROR
   popd
)

REM Never silently fall back to compiling native ARM64 dependencies from source.
set NATIVE_WHEEL_POLICY=
set REQUIREMENTS_FILE=%CLI_SRC%\azure-cli\requirements.py3.windows.txt
if "%ARCH%"=="arm64" (
    set NATIVE_WHEEL_POLICY=--only-binary=cryptography,bcrypt,psutil,cffi,PyNaCl,pywin32,pymsalruntime
    set REQUIREMENTS_FILE=%TEMP_SCRATCH_FOLDER%\requirements.arm64.txt
    %BUILDING_DIR%\python.exe -I %REPO_ROOT%\build_scripts\windows\scripts\prepare_arm64_requirements.py --source %CLI_SRC%\azure-cli\requirements.py3.windows.txt --output !REQUIREMENTS_FILE!
    if errorlevel 1 goto ERROR
    copy !REQUIREMENTS_FILE! %OUTPUT_DIR%\requirements.arm64.txt
    if errorlevel 1 goto ERROR
)
%BUILDING_DIR%\python.exe -Im pip install --no-warn-script-location %NATIVE_WHEEL_POLICY% --requirement %REQUIREMENTS_FILE%
if %errorlevel% neq 0 goto ERROR
if "%ARCH%"=="arm64" (
    %BUILDING_DIR%\python.exe -Im pip check
    if errorlevel 1 goto ERROR
    %BUILDING_DIR%\python.exe -I %REPO_ROOT%\build_scripts\windows\tests\test_native_dependencies.py
    if errorlevel 1 goto ERROR
)

REM Check azure.cli can be executed. This also prints the Python version.
%BUILDING_DIR%\python.exe -Im azure.cli --version
if %errorlevel% neq 0 goto ERROR


pushd %BUILDING_DIR%
%BUILDING_DIR%\python.exe -I %REPO_ROOT%\scripts\compact_aaz.py
if %errorlevel% neq 0 goto ERROR
%BUILDING_DIR%\python.exe -I %REPO_ROOT%\scripts\trim_sdk.py
if %errorlevel% neq 0 goto ERROR
popd

REM Remove pywin32 help file to reduce size.
del %BUILDING_DIR%\Lib\site-packages\PyWin32.chm

if "%TARGET%"=="msi" (
    REM Creating the wbin (Windows binaries) folder that will be added to the path...
    mkdir %BUILDING_DIR%\wbin
    copy %REPO_ROOT%\build_scripts\windows\scripts\az_msi.cmd %BUILDING_DIR%\wbin\az.cmd
    copy %REPO_ROOT%\build_scripts\windows\scripts\azps.ps1 %BUILDING_DIR%\wbin\
    copy %REPO_ROOT%\build_scripts\windows\scripts\az %BUILDING_DIR%\wbin\
) else (
    REM Creating the bin folder that will be added to the path...
    mkdir %BUILDING_DIR%\bin
    copy %REPO_ROOT%\build_scripts\windows\scripts\az_zip.cmd %BUILDING_DIR%\bin\az.cmd
)
if %errorlevel% neq 0 goto ERROR
copy %REPO_ROOT%\build_scripts\windows\resources\CLI_LICENSE.rtf %BUILDING_DIR%
copy %REPO_ROOT%\build_scripts\windows\resources\ThirdPartyNotices.txt %BUILDING_DIR%
copy %REPO_ROOT%\NOTICE.txt %BUILDING_DIR%

REM Remove .py and only deploy .pyc files
pushd %BUILDING_DIR%\Lib\site-packages
for /f %%f in ('dir /b /s *.pyc') do (
    set PARENT_DIR=%%~df%%~pf..
    echo !PARENT_DIR! | findstr /C:\Lib\site-packages\pip\ 1>nul
    if !errorlevel! neq  0 (
        REM Only take the file name without 'pyc' extension: e.g., (same below) __init__.cpython-310
        set FILENAME=%%~nf
        REM Truncate the '.cpython-310' postfix which is 12 chars long: __init__
        REM https://stackoverflow.com/a/636391/2199657
        set BASE_FILENAME=!FILENAME:~0,-12!
        REM __init__.pyc
        set pyc=!BASE_FILENAME!.pyc
        REM Delete ..\__init__.py
        del !PARENT_DIR!\!BASE_FILENAME!.py
        REM Copy to ..\__init__.pyc
        copy %%~f !PARENT_DIR!\!pyc! >nul
        REM Delete __init__.pyc
        del %%~f
    ) ELSE (
        REM pip source code is required when install packages from source code
        echo --SKIP !PARENT_DIR! under pip
    )
)
popd

REM Remove empty __pycache__ directories because .pyc files are already moved to parent directories
echo remove pycache
for /d /r %BUILDING_DIR%\Lib\site-packages\ %%d in (__pycache__) do (
    if exist %%d rmdir /s /q "%%d"
)

REM Remove dist-info
echo remove dist-info
pushd %BUILDING_DIR%\Lib\site-packages
for /d %%d in ("azure*.dist-info") do (
    if exist %%d rmdir /s /q "%%d"
)
popd


if "%TARGET%"=="msi" (
    echo Building MSI...
    %BUILDING_DIR%\python.exe -I %REPO_ROOT%\build_scripts\windows\scripts\verify_runtime.py --root %BUILDING_DIR% --arch %ARCH% --all
    if errorlevel 1 goto ERROR
    msbuild /t:rebuild /p:Configuration=Release /p:Platform=%ARCH% /p:WixToolPath=%WIX_DIR% /p:WixTargetsPath=%WIX_DIR%\Wix.targets /p:WixTasksPath=%WIX_DIR%\WixTasks.dll %REPO_ROOT%\build_scripts\windows\azure-cli.wixproj
) else (
    echo Building ZIP...
    %BUILDING_DIR%\python.exe -I %REPO_ROOT%\build_scripts\windows\scripts\verify_runtime.py --root %BUILDING_DIR% --arch %ARCH% --all
    if errorlevel 1 goto ERROR
    "%ProgramFiles%\7-Zip\7z.exe" a -tzip "%OUTPUT_DIR%\%PACKAGE_NAME%.zip" "%BUILDING_DIR%\*"
)

if %errorlevel% neq 0 goto ERROR

echo Output Dir: %OUTPUT_DIR%

goto END

:ERROR
echo Error occurred, please check the output for details.
exit /b 1

:END
exit /b 0
popd
