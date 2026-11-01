# Third-party notices

## MAME — CPS-2 decryption (cps2_decrypt.py)

`cps2_decrypt.py` (and `opcrypt.py`, which uses it) is a Python port of MAME's
`src/mame/capcom/cps2crypt.cpp` and the key handling in `src/mame/capcom/cps2.cpp`.
Both files are distributed under the BSD-3-Clause license:

```
license:BSD-3-Clause
copyright-holders: Paul Leaman, Andreas Naive, Nicola Salmoria, Charles MacDonald

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this
   list of conditions and the following disclaimer in the documentation and/or
   other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors may
   be used to endorse or promote products derived from this software without
   specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Dependencies (installed separately, not included)

| Package | Used for | License |
|---|---|---|
| FastAPI, Starlette, Pydantic | web server | MIT |
| Uvicorn | web server | BSD-3-Clause |
| NumPy | decryption, graphics | BSD-3-Clause |
| Capstone | 68000 disassembly (input editing) | BSD-3-Clause |
| httpx | tests and tools | BSD-3-Clause |
| jsdom (tests/ui, dev only) | browser-side tests | MIT |

## References (no code included)

Memory addresses, the hitbox colour convention and notes from:

- Dammit / MZ / Felineki's mame-rr hitbox scripts and pof's SSF2X training lua
- ssf2xj-recomp (github.com/andreoka-debug/ssf2xj-recomp, GPL-3.0), built on Tommy McLeroy's cps2recomp (github.com/tmcleroy/cps2recomp, GPL-3.0): memory addresses cross-checked against its notes
- the FBNeo / Fightcade Super Turbo training scripts
- the SuperCombo wiki

No code from any of these is included.
