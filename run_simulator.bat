@echo off
echo ===============================================
echo    HELLCATS OVER THE PACIFIC - Enhanced Edition
echo ===============================================
echo.
echo Installing required packages...
pip install -r requirements.txt
echo.
echo Starting flight simulator...
echo.
python hellcat_sim.py
pause