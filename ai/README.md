# ai/ — classifier and defender (owner: Vishwas)

| File | What |
|---|---|
| `features.py` | Shared preprocessing: dB above the calibrated noise floor / 20 |
| `dataset.py` | Synthetic + live-world spectrogram windows (`python -m ai.dataset`) |
| `train.py` | PyTorch training, export to `weights/cnn_v1.npz`, report with confusion matrix (`python -m ai.train`) |
| `cnn.py` | NumPy inference, 3-window vote, closed-form Grad-CAM (12×32) |
| `defender.py` | AegisDefender: per-class responses, backups, follower detection, hop guard, recovery, relays |
| `localize.py` | RSSI least-squares jammer localisation with NLOS rejection and a 95 % radius |
| `weights/` | Trained weights (committed) and `report.json` |

`data/` is generated and not committed.

## RL hopping agent (Phase 6)

`rl.py`: tabular Q-learning agent (256 states x 5 moves: stay, hop, keyed, power, calm) trained in the simulator
from packet loss and channel energy only. `python -m ai.rl --train` writes `weights/rl_q.json`. Benchmark row `rl`.
