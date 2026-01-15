@echo off
:: H Translator - Context Menu Uninstall
:: Run as Administrator

echo ============================================
echo   H Translator - Context Menu Uninstall
echo ============================================
echo.

echo Removing context menu entries...
reg delete "HKCR\*\shell\HTranslator" /f >nul 2>&1
reg delete "HKCR\SystemFileAssociations\.txt\shell\HTranslator" /f >nul 2>&1
reg delete "HKCR\SystemFileAssociations\.md\shell\HTranslator" /f >nul 2>&1
reg delete "HKCR\SystemFileAssociations\.html\shell\HTranslator" /f >nul 2>&1

echo.
echo ============================================
echo   Uninstall Complete!
echo ============================================
echo.
pause
