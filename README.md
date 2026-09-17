# AGIMUD: AGENTIC INTELLIGENCE AND MULTI-USER DUNGEONS

## Customize your Simulated World

For editing your world characters, objects and scene names, modify `objects_names.txt`, `characters_names.txt` and `scenes_names.txt` if needed.

Then edit `world_vocabulary.json`, `generation_config.json`, `world_dynamics.json` to change the world and assets mechanics.

## Generate and Simulate Worlds

Run the following commands
```
python swm_generate.py
```
This will generate several jsons (`characters.json`, `objects.json`, `rules.json`, `scenes.json`, `world_states.json`, `action_catalog.json`, `condition_registry.json`, `character_graph.json` and concatenating all the info in `knowledge_base.json` ) that will be exported in `world_X-Y/` where X-Y is the date of the generation.

Then run this to execute the simulated world:
```
python swm_run.py --new
```
This will create a new world, it will export in the world_X-Y folder the `world_state_runtime.json` and the text log `run_X-Y.txt` with all the events and visualization epochs.
You can reload the world state by discarting the `--new` flag when running the server again.


Then, to quit and save your world, press Ctrl+C

## Social Reasoning and Affective Methods

To run the theories of mind, check (and modify as needed) the `reasoning_tests.json` and run tests with:
```
python swm_reason.py
```
To run emotion tests, check (and modify as needed) the `emotion_tests.json` and run the tests with:
```
python swm_emotion.py
```
The `swm.py` and `swm_run.py` world simulations runs epochs including the integration and analysis of behavior, values, governance and belief motors, as well as emotions, goals and action rules.

## Network Connections

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

Create an agent instance using the submodule [LM Studio Python Wrapper](https://github.com/dberga/lmstudio-python-wrapper) and let it join a SWM Server session, with many parameters such as chat style "dramatic", "funny", etc.; selected AI model to load, temperature, agent chat frequency, MCP selection, and character in case of roleplaying as a specific character. See this example:
```
python swm_run_agent_client.py --chat_style "dramatic" --actions_enabled
```
For the case of P2P, an agent can be run as host or as joiner:
```
python swm_run_agent_p2p.py --host
```
```
python swm_run_agent_p2p.py --join
```
### Multiple Worlds Analysis
You can either run through Linux/MAC the script `run_worlds.sh` or in Windows `run_worlds.bat` to generate and run distinct instances of world simulations (the number of worlds and number of characters are parameterized. See here creating 10 worlds of 8 characters each.
```
sh run_worlds.sh 10 8
```
Alternatively you can analyze specific world folders directly from those you have created:
```
python swm_analyze.py --worlds "worldsim1,worldsim2,worldsim3,worldsim4,worldsim5,worldsim6,worldsim7,worldsim8,worldsim9"
```
This will plot box plots, temporal (per tick/epoch) line plots, scatter and co-occurrence matrixes as well as run quantitative analysis between worlds and per world/character factors, including actions, ai states, emotion states and status variables (health, stamina, morale, thirst, hunger).
