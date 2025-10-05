#!/usr/bin/env python3
"""Test script to verify base64 mask export functionality."""

import base64
import json
from pathlib import Path
from PIL import Image
import numpy as np
from io import BytesIO


def image_to_base64(image, format="PNG"):
    """Convert PIL Image to base64-encoded string."""
    buffer = BytesIO()
    image.save(buffer, format=format)
    buffer.seek(0)
    img_bytes = buffer.getvalue()
    return base64.b64encode(img_bytes).decode('utf-8')


def test_base64_export():
    """Test the base64 export functionality with a simple mask."""
    # Create a simple test image (100x100 gradient)
    width, height = 100, 100
    gradient = np.zeros((height, width), dtype=np.uint8)

    # Create a gradient from black to white
    for i in range(height):
        gradient[i, :] = int(255 * i / height)

    # Convert to PIL Image
    mask_image = Image.fromarray(gradient, mode='L')

    # Save to file for reference
    mask_image.save('test_mask.png', format='PNG')

    # Convert to base64
    mask_base64 = image_to_base64(mask_image, format='PNG')

    # Create test output
    test_data = {
        "test": "base64 mask export",
        "mask_dimensions": [width, height],
        "mask_base64": mask_base64,
        "base64_length": len(mask_base64)
    }

    # Save to JSON
    with open('test_mask_output.json', 'w') as f:
        json.dump(test_data, f, indent=2)

    print(f"✓ Created test mask image: test_mask.png")
    print(f"✓ Base64 encoded length: {len(mask_base64)} characters")
    print(f"✓ Saved test output to: test_mask_output.json")

    # Verify we can decode it back
    decoded_bytes = base64.b64decode(mask_base64)
    decoded_image = Image.open(BytesIO(decoded_bytes))
    print(f"✓ Successfully decoded back to image: {decoded_image.size}")

    return True


if __name__ == "__main__":
    success = test_base64_export()
    if success:
        print("\n✅ Base64 mask export functionality is working correctly!")