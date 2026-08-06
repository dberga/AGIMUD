#!/bin/bash
echo "Accessing the .lmstudio root folder"
cd $HOME/.lmstudio
lmstudiopath=$(pwd -W)
echo "Checking NPM version"
vers=$(npm -v 2>&1)
if [ $? -eq 0 ]; then
    echo "npm version: $vers"
    echo "Downloading and extracting web-search-mcp"
    wget https://github.com/mrkrsl/web-search-mcp/releases/download/v0.3.2/web-search-mcp-v0.3.2.zip
    mkdir web-search-mcp-v0.3.2
    unzip web-search-mcp-v0.3.2.zip -d web-search-mcp-v0.3.2

    echo "Installing web-search-mcp"
    cd web-search-mcp-v0.3.2
    npm install
    npm run build
    cd ..
    echo "Installing playwright api"
    npx playwright install
    echo "Installing duckduckgo plugin"
    lms get danielsig/duckduckgo

    echo "Replacing mcp.json"
    sed "s|{{LMSTUDIO_PATH}}|${lmstudiopath}|g" mcp.json.template > mcp.json
    echo "Note: now you should activate the search tools including duckduckgo, mcp/playwright and mcp/web-search in your LM Studio."

else
    echo "Error: $vers. Please install npm from https://nodejs.org/en/download"
fi