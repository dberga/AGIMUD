# Human-Agentic World Architecture (HAWA)

## Customize your Simulated World

For editing your world characters, objects and scene names, modify `objects_names.txt`, `characters_names.txt` and `scenes_names.txt` if needed.

Then edit `world_vocabulary.json`, `generation_config.json`, `action_catalog.json`,  `world_dynamics.json` to change the world and assets mechanics.

## Generate and Simulate Worlds

Run the following commands
```
python swm_generate.py
```
This will generate several jsons (`characters.json`, `objects.json`, `rules.json`, `scenes.json`, `world_states.json` and concatenating all the info in `knowledge_base.json` ) that will be exported in `world_X-Y/` where X-Y is the date of the generation.

Then run this to execute the simulated world:
```
python swm_run.py --fps 1.0 --new
```
This will create a new world, it will export in the world_X-Y folder the `world_state_runtime.json` and the text log `run_X-Y.txt` with all the events and visualization epochs.

Then, to quit and save your world, press Ctrl+C

## Social Reasoning Methods

To run the theories of mind, check (and modify as needed) the `reasoning_tests.json` and run tests with:
```
python swm_reason.py
```
## Network Connections

### Centralized mode (Server - Client)

Check connections configuration on the `network_server_config.json` and `network_client_config.json`. By default this is on localhost and port 5000-5001.

First copy or generate world to specific folder `world_centralized`:
```
python swm_generate.py --folder world_centralized
```
Then run a new server:
```
python swm_run_server.py --new
```
Clients can connect now, through:
```
python swm_run_client.py
```
### P2P mode (Host - Joiner)
Check connections configuration on the `network_p2p_config.json` and `network_p2p_join_config.json`. By default this is on localhost and port 6000-6002 and 7000 for the signaling server.

First copy or generate world to specific folder `world_p2p`:
```
python swm_generate.py --folder world_p2p
```
Then host the p2p host:
```
python swm_run_p2p.py --host --world world_p2p
```
(or directly use)
```
python swm_run_p2p.py --host --new
```

```
Then joiner Peers can connect now, through:
```
python swm_run_p2p.py --join --config network_p2p_join_config.json
```
