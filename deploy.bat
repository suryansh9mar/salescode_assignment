@echo off
REM Deployment script for Intelligent Interruption Agent (Windows)

echo ======================================================================
echo   INTELLIGENT INTERRUPTION AGENT - DEPLOYMENT
echo ======================================================================
echo.

REM Check if .env file exists
if not exist .env (
    echo ERROR: .env file not found!
    echo Please create .env file with your API keys.
    exit /b 1
)

echo Checking environment variables...
echo.

REM Display configuration (without showing full keys)
echo LiveKit URL: %LIVEKIT_URL%
echo API Keys configured: 
if defined DEEPGRAM_API_KEY echo   - Deepgram: YES
if defined CARTESIA_API_KEY echo   - Cartesia: YES
if defined GOOGLE_API_KEY echo   - Google: YES
echo.

echo ======================================================================
echo   STARTING AGENT IN PRODUCTION MODE
echo ======================================================================
echo.
echo The agent will connect to: %LIVEKIT_URL%
echo.
echo Press Ctrl+C to stop the agent
echo.

REM Start the agent in production mode
python examples\voice_agents\intelligent_interruption_agent.py start

echo.
echo ======================================================================
echo   AGENT STOPPED
echo ======================================================================

