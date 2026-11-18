# GGUFly Windows

GGUFly is a Windows terminal manager for GGUF models. It requires Python 3.10 or later and a Windows build of llama.cpp that you install and manage separately.

1. Double-click `GGUFly.cmd`. GGUFly checks the saved path to `llama-server.exe` first, then searches your Windows `PATH`.
2. If GGUFly cannot find the engine, press **D** to open the official releases page. Download a Windows build for your hardware and keep its DLLs with `llama-server.exe`. If the NVIDIA CUDA build has a separate runtime archive, extract it into the same folder. Press **G**, then **Enter** to set the executable path. You can also add the engine folder to `PATH` and reopen the terminal.
3. Press **F** to choose a model folder or **O** to add a single GGUF file. Select a model with **↑/↓** and press **Enter** to open its settings. Press **L** to launch with the current settings and follow the scrolling server log. When the server is running, press **C** to open chat in your browser. Press **Esc** to return to settings.

Green means the server is running, yellow means the model is loading, and red means the server stopped or exited.

In settings, use **↑/↓** to select a parameter and **Enter** to edit it. Use **←/→** to cycle through choices. Press **S** to save changes or **A** to save them as a named preset. Presets appear on the main screen, where **N** renames them and **Del** deletes them.

Settings include context size, GPU layers, CPU threads, Flash Attention, batch and microbatch sizes, parallel slots, KV cache types, sampling, reasoning budget, maximum output tokens, vision projector, MTP, LoRA, and the local port. **Engine default** lets llama.cpp choose the value. MTP, vision, and some advanced settings require engine and model support.

To upgrade, extract the new engine into a separate folder. Press **X** to stop the server, then **G**, then **Enter** to set the new path. If you manage the engine through `PATH`, press **A** on the Engine screen to switch back to automatic detection.

[Official llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)
