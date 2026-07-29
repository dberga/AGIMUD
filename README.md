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

To run the theories of mind, run the minimal and extended tests here:
```
python swm_reason.py
python reasoning_tests.py
```
