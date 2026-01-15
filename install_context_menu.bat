@echo off
:: H Translator - Context Menu Install
:: Run as Administrator

echo ============================================
echo   H Translator - Context Menu Install
echo ============================================
echo.

set "SCRIPT_DIR=%~dp0"
set "BAT_FILE=%SCRIPT_DIR%translate.bat"
set "ICON_PATH=%SCRIPT_DIR%icon.ico"

echo Install path: %SCRIPT_DIR%
echo Batch file: %BAT_FILE%
echo Icon: %ICON_PATH%
echo.

echo [1/2] Registering menu for all files...
reg add "HKCR\*\shell\HTranslator" /ve /d "H Translator" /f >nul
reg add "HKCR\*\shell\HTranslator" /v "Icon" /d "%ICON_PATH%" /f >nul
reg add "HKCR\*\shell\HTranslator\command" /ve /d "\"%BAT_FILE%\" \"%%1\"" /f >nul

echo [2/2] Registering for file types...
for %%e in (.txt .md .html) do (
    reg add "HKCR\SystemFileAssociations\%%e\shell\HTranslator" /ve /d "H Translator" /f >nul
    reg add "HKCR\SystemFileAssociations\%%e\shell\HTranslator" /v "Icon" /d "%ICON_PATH%" /f >nul
    reg add "HKCR\SystemFileAssociations\%%e\shell\HTranslator\command" /ve /d "\"%BAT_FILE%\" \"%%1\"" /f >nul
)

echo.
echo ============================================
echo   Install Complete!
echo ============================================
echo.
pause
