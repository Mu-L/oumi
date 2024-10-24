import collections
from typing import Any, Dict, List, Optional, Set

import numpy as np
import torch

from oumi.core.collators.text_collator_with_padding import TextCollatorWithPadding
from oumi.core.tokenizers.base_tokenizer import BaseTokenizer
from oumi.utils.logging import logger

_PIXEL_VALUES_KEY = "pixel_values"


class VisionLanguageCollatorWithPadding:
    def __init__(
        self,
        tokenizer: BaseTokenizer,
        *,
        max_length: Optional[int],
        truncation: bool = False,
        label_ignore_index: Optional[int] = None,
    ):
        """Custom collator for multi-modal vision-language training.

        Args:
        tokenizer: The tokenizer used for encoding the data.
        max_length: Padding length.
        truncation: Whether to truncate long inputs to `max_length`.
            If False, the long inputs are preserved as is even if they exceed
            `max_length`. Only has effect if `max_length` is specified.
        label_ignore_index:  If set, then label values of tokens that shouldn't
            contribute to the loss computation will be replaced by this special value.
        """
        self._text_collator: TextCollatorWithPadding = TextCollatorWithPadding(
            tokenizer=tokenizer,
            max_length=max_length,
            truncation=truncation,
            label_ignore_index=label_ignore_index,
        )

    def __call__(self, batch) -> Dict[str, Any]:
        """Custom collator for multi-modal  vision-language training.

        Args:
            batch: List of batch items.

        Returns:
            Dict[str, torch.Tensor]: Processed batch.
        """
        # Collate batch prompts
        collated_batch = self._text_collator(batch)  # type: ignore
        known_input_names: Set[str] = set(collated_batch.keys()).union(
            {_PIXEL_VALUES_KEY}
        )
        other_input_names: Set[str] = set()

        images = []
        for item in batch:
            # TODO Consider relaxing this constraint: a vision/language model
            # can handle text-only inputs e.g., a follow-up to an answer,
            # or image-only inputs e.g., captioning.
            if _PIXEL_VALUES_KEY not in item:
                raise ValueError(
                    f"Item doesn't contain '{_PIXEL_VALUES_KEY}' key. "
                    f"Available keys: {item.keys()}"
                )
            images.append(item[_PIXEL_VALUES_KEY])

            for key in item:
                if (
                    key
                    and (key not in known_input_names)
                    and (key not in other_input_names)
                ):
                    other_input_names.add(key)

        # Collate batch images.
        pixel_values = self.collate_images(images)

        # Add images to other inputs.
        collated_batch[_PIXEL_VALUES_KEY] = pixel_values

        if len(other_input_names) > 0:
            logger.warning(f"Unknown input names: {other_input_names}")
            other_inputs: Dict[str, List[Any]] = collections.defaultdict(list)
            for item in batch:
                for input_name in other_input_names:
                    if input_name not in item:
                        raise ValueError(
                            f"Item doesn't contain '{input_name}' key. "
                            f"Available keys: {item.keys()}"
                        )
                    other_inputs[input_name].append(item[input_name])

            for input_name, values_list in other_inputs.items():
                logger.info(f"{input_name}: {len(values_list)} elements")

                if isinstance(values_list[0], np.ndarray):
                    values_list = [torch.from_numpy(item) for item in values_list]
                    shapes_list = [item.shape for item in values_list]
                    logger.info(f"'{input_name}': {shapes_list}")

                if isinstance(values_list[0], torch.Tensor):
                    collated_value = torch.stack(values_list)
                elif isinstance(values_list[0], np.ndarray):
                    collated_value = torch.stack(
                        [torch.from_numpy(item) for item in values_list]
                    )
                else:
                    raise ValueError(
                        f"'{input_name}': Unsupported type: {type(values_list[0])}"
                    )
                collated_batch[input_name] = collated_value

        return collated_batch

    def collate_images(self, images) -> torch.Tensor:
        """Collate images for multi-modal training.

        Args:
            images: List of images to collate.

        Returns:
            torch.Tensor: Batch of processed images.
        """
        if len(images) == 0:
            raise ValueError("No images found in the batch")

        if isinstance(images[0], torch.Tensor):
            return torch.stack(images)
        elif isinstance(images[0], np.ndarray):
            return torch.stack([torch.from_numpy(img) for img in images])
        elif isinstance(images[0], list):
            return torch.tensor(images)
        else:
            raise ValueError(f"Unsupported image type: {type(images[0])}")
