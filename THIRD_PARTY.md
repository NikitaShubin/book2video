# Third-party components and notices

`book2video` orchestrates several external components. None of their model
weights or binaries are stored in this repository, except as pulled into the
Docker image at build time.

| Component | Role | Distribution terms |
| --- | --- | --- |
| [TeraTTSv2](https://huggingface.co/TeraSpace/TeraTTSv2) | Text-to-speech model | OpenRAIL-M; reviewed and attributed here, not bundled |
| ffmpeg | `atempo` time scaling, encoding, muxing | Depends on the distribution build; see the image package metadata |
| Playwright | Headless site screenshots for link previews | Apache-2.0 |
| Chromium / headless shell | Browser used by Playwright | BSD-style and other open-source licenses |
| poppler (`pdftoppm`) | PDF page rendering | GPL-2.0-or-later |
| Pillow | Frame composition and QR images | HPND |
| qrcode | QR generation | BSD-3-Clause |
| NumPy, soundfile, transformers | Audio and model runtime | See each package's license |
| onnxruntime | CPU inference (default image) | MIT |
| onnxruntime-gpu, NVIDIA CUDA/cuDNN runtime packages | Optional CUDA inference (GPU image only) | MIT for onnxruntime-gpu; NVIDIA runtime packages under their own terms |
| BeautifulSoup, lxml, PyYAML, requests | EPUB and link processing | See each package's license |

TeraTTSv2 is downloaded into the `hf-cache` volume on first use. It is not
redistributed by this project. If you publish generated audio, check the model
card and the OpenRAIL-M use restrictions for your case.

The GPU image pulls NVIDIA CUDA and cuDNN user-space wheels from PyPI at build
time. They are not stored in this repository; the host driver remains the
user's responsibility.

The project source is released under the MIT License; see `LICENSE`. That
license does not change the terms of the third-party components above. This
notice is not legal advice.
