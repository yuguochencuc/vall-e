#!/usr/bin/env python3
# Copyright    2023                            (authors: Feiteng Li)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Phonemize Text and EnCodec Audio.

Usage example:
    python3 bin/infer.py \
        --decoder-dim 128 --nhead 4 --num-decoder-layers 4 --model-name valle \
        --text-prompts "Go to her." \
        --audio-prompts ./prompts/61_70970_000007_000001.wav \
        --output-dir infer/demo_valle_epoch20 \
        --checkpoint exp/valle_nano_v2/epoch-20.pt

"""
import argparse
import logging
import os
from pathlib import Path

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

import torch
import torchaudio

from valle.data import (
    AudioTokenizer,
    TextTokenizer,
    tokenize_audio,
    tokenize_text,
)
from valle.data.collation import get_text_token_collater
from valle.modules import add_model_arguments, get_model


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--text-prompts",
        type=str,
        default="",
        help="Text prompts which are separated by |.",
    )

    parser.add_argument(
        "--audio-prompts",
        type=str,
        default="",
        help="Audio prompts which are separated by | and should be aligned with --text-prompts.",
    )

    parser.add_argument(
        "--text",
        type=str,
        default="To get up and running quickly just follow the steps below.",
        help="Text to be synthesized.",
    )

    # model
    add_model_arguments(parser)

    parser.add_argument(
        "--text-tokens",
        type=str,
        default="data/tokenized/unique_text_tokens.k2symbols",
        help="Path to the unique text tokens file.",
    )

    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("exp/vallf_nano_full/checkpoint-100000.pt"),
        help="Path to the saved checkpoint.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("infer/demo"),
        help="Path to the tokenized files.",
    )

    return parser.parse_args()


@torch.no_grad()
def main():
    args = get_args()
    text_tokenizer = TextTokenizer()
    text_collater = get_text_token_collater(args.text_tokens)
    audio_tokenizer = AudioTokenizer()

    device = torch.device("cpu")
    if torch.cuda.is_available():
        device = torch.device("cuda", 0)

    model = get_model(args)
    if args.checkpoint.is_file():
        checkpoint = torch.load(args.checkpoint, map_location=device)
        missing_keys, unexpected_keys = model.load_state_dict(
            checkpoint["model"], strict=True
        )
        assert not missing_keys
        # from icefall.checkpoint import save_checkpoint
        # save_checkpoint(f"{args.checkpoint}", model=model)

    model.to(device)
    model.eval()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    text_prompts, text_prompts_lens = text_collater(
        [
            tokenize_text(
                text_tokenizer, text=" ".join(args.text_prompts.split("|"))
            )
        ]
    )

    audio_prompts = []
    for n, audio_file in enumerate(args.audio_prompts.split("|")):
        encoded_frames = tokenize_audio(audio_tokenizer, audio_file)
        if False:
            samples = audio_tokenizer.decode(encoded_frames)
            torchaudio.save(f"{args.output_dir}/p{n}.wav", samples[0], 24000)

        audio_prompts.append(encoded_frames[0][0])

    assert len(args.text_prompts.split("|")) == len(audio_prompts)

    audio_prompts = torch.concat(audio_prompts, dim=-1).transpose(2, 1)

    for n, text in enumerate(args.text.split("|")):
        logging.info(f"synthesize text: {text}")
        text_tokens, text_tokens_lens = text_collater(
            [tokenize_text(text_tokenizer, text=text)]
        )

        text_tokens = torch.concat(
            [text_prompts[:, :-1], text_tokens[:, 1:]], dim=-1
        )
        text_tokens_lens += text_prompts_lens - 2

        # synthesis
        encoded_frames = model.inference(
            text_tokens.to(device),
            text_tokens_lens.to(device),
            audio_prompts.to(device),
        )
        samples = audio_tokenizer.decode(
            [(encoded_frames.transpose(2, 1), None)]
        )
        # store
        torchaudio.save(f"{args.output_dir}/{n}.wav", samples[0].cpu(), 24000)


torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch._C._jit_set_profiling_executor(False)
torch._C._jit_set_profiling_mode(False)
torch._C._set_graph_executor_optimize(False)
if __name__ == "__main__":
    formatter = (
        "%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s"
    )
    logging.basicConfig(format=formatter, level=logging.INFO)
    main()
