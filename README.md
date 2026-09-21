# AGIMUD: AGENTIC INTELLIGENCE AND MULTI-USER DUNGEONS

## Customize your Simulated World

For editing your world characters, objects and scene names, modify `objects_names.txt`, `characters_names.txt` and `scenes_names.txt` if needed.

Then edit `world_vocabulary.json`, `generation_config.json`, `world_dynamics.json` to change the world and assets mechanics.

## Generate and Run Simulated Worlds

### World Generation
Run the following commands
```
python swm_generate.py --folder world_sample --characters 8
```
This will generate several jsons (`characters.json`, `objects.json`, `rules.json`, `scenes.json`, `world_states.json`, `action_catalog.json`, `condition_registry.json`, `character_graph.json` and concatenating all the info in `knowledge_base.json` ) that will be exported in `world_X-Y/` where X-Y is the date of the generation.

You can export the latex tables from the Charcter Profiles, Condition Registry and Rules with:
```
python chargraph2latex.py --input world_sample/character_graph.json --output world_sample
python condition_registry2latex.py --input world_sample/condition_registry.json --output world_sample
python rules2latex.py --input world_sample/rules.json --output world_sample
```

### World Runner
Then run this to execute a new simulated world (note: remove --new to continue an existing session):
```
python swm_run.py --new --world world_sample 
```
This will create a new world, it will export in the world_X-Y folder the `world_state_runtime.json` and the text log `run_X-Y.txt` with all the events and visualization epochs. Note: You can reload the world state by discarting the `--new` flag when running the server again.

Then, to quit and save your world, press Ctrl+C.

### Interactive Mode
Add the flag "--interact" to execute the runner's epochs step by step. 
```
python swm_run.py --world world_sample --interact
```
Here are the terminal parsed commands (same as for clients, see network section):
```
============================================================
SWM INTERACTIVE COMMANDS
============================================================
  [Enter]              - Toggle PAUSE/LIVE mode
  help                 - Show this help menu
  summary              - Request world summary from server
  catalog              - List available actions in catalog
  var                  - List available variables
  list                 - List characters, objects and scenes
  action <Name> <ACTION> - Force character action intent
  set char <Name> <var> <val> - Modify character status/vars
  set world <key> <val> - Modify global world state
  save                 - Save current world state on server
  mode                 - Show current server mode
  chat <message>       - Send a chat message to all clients
  history              - Request the most recent run log
  chatlog              - Request the chat history
  resume               - Resume updates (exit pause mode)
  q / quit / exit      - Disconnect and exit
============================================================
```
## Social Reasoning and Affective Methods (ToM + Emotion Tests)

To run the theories of mind, check (and modify as needed) the `reasoning_tests.json` and run tests with:
```
python swm_reason.py > results_reasoning.txt
```
To run emotion tests, check (and modify as needed) the `emotion_tests.json` and run the tests with:
```
python swm_emotion.py > results_emotion.txt
```
The `swm.py` and `swm_run.py` world simulations runs epochs including the integration and analysis of behavior, values, governance and belief motors, as well as emotions, goals and action rules. You can export the latex tables with:
```
python emotion2latex.py --input results_emotion.txt
python emotion2reasoning.py --input results_reasoning.txt
```

## Network Connections (MUDs + Agents)

### Centralized mode (Server - Client)

Check connections configuration on the `network_server_config.json` and `network_client_config.json`. By default this is on localhost and port 5000-5001.

First copy or generate world to specific folder `world_centralized`:
```
python swm_generate.py --folder world_centralized
```
Then run a new server:
```
python swm_run_server.py --world world_centralized --new
```
Clients can connect now, through:
```
python swm_run_client.py
```
You can reload the world state by discarting the `--new` flag when running the server again.

### P2P mode (Host - Joiner)
Check connections configuration on the `network_p2p_config.json` and `network_p2p_join_config.json`. By default this is on localhost and port 6000-6002 and 7000 for the signaling server.

First copy or generate world to specific folder `world_p2p`:
```
python swm_generate.py --folder world_p2p
```
Then run a new p2p peer host:
```
python swm_run_p2p.py --host --world world_p2p --new
```
Then joiner Peers can connect now, through:
```
python swm_run_p2p.py --join --world world_p2p --config network_p2p_join_config.json
```
You can reload the world state by discarting the `--new` flag when running the p2p host again.

### Agent Clients and Peers
This section is a buildup of agents that interact with the world runners (as in a MUD), being able to chat describing what is going on, and request setting actions and variables for characters.

Create an agent instance using the submodule [LM Studio Python Wrapper](https://github.com/dberga/lmstudio-python-wrapper) and let it join a SWM Server session, with many parameters such as chat narrative style "dramatic", "funny"..., the selected AI model to load, model temperature, agent chat frequency, MCP selection, and other variables such as character selection in case of roleplaying as a specific character. Also a flag to enable the agent to set actions and variables using the chat parser helper.
```
python swm_run_agent_client.py --chat_style "dramatic"
```
For the case of P2P, an agent can be run as host or as joiner:
```
python swm_run_agent_p2p.py --host --new --world world_p2p --chat_style "creepy narration from a GM" --agent_chat_frequency 10 --actions_enabled
```
```
python swm_run_agent_p2p.py --join --world world_p2p --chat_style "funny and descriptive" --agent_chat_frequency 3 --config network_p2p_join_config.json
```
## Analyzing Multiple Worlds
You can either run through Linux/MAC the script `run_worlds.sh` or in Windows `run_worlds.bat` to generate and run distinct instances of world simulations (the number of worlds, number of characters, number of objects and max epochs are parameterized. See here creating by default 9 worlds of 8 characters and 15 objects each for 10080 epochs (24h of simulated world time).
```
sh run_worlds.sh 9 8 15 10080
```
Alternatively you can analyze specific world folders directly from those you have created:
```
python swm_analyze.py --worlds "world1,world2,world3,world4,world5,world6,world7,world8,world9"
```
This will plot box plots, temporal (per tick/epoch) line plots, scatter and co-occurrence matrixes as well as run quantitative analysis between worlds and per world/character factors, including actions, ai states, emotion states and status variables (health, stamina, morale, thirst, hunger).
