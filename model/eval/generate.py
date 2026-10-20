"""Get completions out of a local model, or off disk.

Generation is kept behind this one seam so the scorer never knows what produced
the Dart. That is what makes the baseline honest: the base model, the tuned
model, and a directory of files Claude wrote all reach the checker by the same
path and are judged by the same rules.

torch and transformers are imported lazily. Scoring must work on a machine with
no CUDA and no ML stack -- the checker is pure Python, and refusing to run it
because bitsandbytes is missing would be absurd.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

HERE = Path(__file__).resolve().parent

# 6 GB of VRAM is the whole constraint. 2048 tokens of output is roughly a
# 200-line Dart file, which is past the 150-line ceiling the rules enforce --
# anything longer is a failure we want to see, not a truncation we caused.
MAX_NEW_TOKENS = 2048


class Generator(Protocol):
    name: str

    def complete(self, system: str, instruction: str) -> str: ...


@dataclass
class DirGenerator:
    """Read answers from disk: one <prompt id>.dart per prompt.

    For scoring something that was not produced here -- Claude's output, a
    hand-written control, a run from another machine.
    """

    root: Path
    name: str = "dir"

    def complete(self, system: str, instruction: str) -> str:  # noqa: ARG002
        raise NotImplementedError("DirGenerator is read by prompt id, see read_for()")

    def read_for(self, prompt_id: str) -> str:
        for suffix in (".dart", ".txt", ".md"):
            path = self.root / f"{prompt_id}{suffix}"
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        return ""


class HfGenerator:
    """A local Hugging Face causal LM, optionally 4-bit.

    Greedy by default. Sampling would make two runs of the same checkpoint
    disagree, and the entire point of this harness is comparing runs.
    """

    def __init__(
        self,
        model_id: str,
        *,
        adapter: str | None = None,
        four_bit: bool = True,
        max_new_tokens: int = MAX_NEW_TOKENS,
        temperature: float = 0.0,
    ):
        import torch  # noqa: PLC0415
        from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

        self.name = adapter or model_id
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self._torch = torch

        kwargs: dict = {"dtype": torch.bfloat16, "device_map": "auto"}
        if four_bit:
            from transformers import BitsAndBytesConfig  # noqa: PLC0415

            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kwargs)

        if adapter:
            from peft import PeftModel  # noqa: PLC0415

            self.model = PeftModel.from_pretrained(self.model, adapter)

        self.model.eval()

    def complete(self, system: str, instruction: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": instruction},
        ]
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)

        with self._torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=self.temperature > 0,
                temperature=self.temperature or None,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        # Slice off the prompt; decoding the whole sequence would feed the
        # system prompt back into the extractor, fences and all.
        return self.tokenizer.decode(
            output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True
        )


def load_system(condition: str) -> str:
    """`bare` is what a tuned model should need; `full` is the prompt it must beat."""
    path = HERE / f"system_{condition}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"no system prompt for condition '{condition}' at {path}")
    return path.read_text(encoding="utf-8").strip()
