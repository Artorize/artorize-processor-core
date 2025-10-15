"""Visualize the difference between RGB and grayscale reconstruction."""
import numpy as np
from PIL import Image

# Load both reconstructions
rgb_recon = np.asarray(Image.open("_test_rgb_reconstructed.png"))
gray_recon = np.asarray(Image.open("_test_gray_reconstructed.png"))

# Compute absolute difference
diff = np.abs(rgb_recon.astype(np.int16) - gray_recon.astype(np.int16)).astype(np.uint8)

# Amplify for visualization
diff_amplified = np.clip(diff * 10, 0, 255).astype(np.uint8)

# Save difference maps
Image.fromarray(diff).save("_test_difference.png")
Image.fromarray(diff_amplified).save("_test_difference_amplified.png")

# Statistics per channel
print("Per-channel error analysis:")
for i, channel in enumerate(['R', 'G', 'B']):
    ch_diff = diff[:, :, i]
    print(f"\n{channel} channel:")
    print(f"  Mean error: {ch_diff.mean():.2f}")
    print(f"  Max error: {ch_diff.max()}")
    print(f"  Std dev: {ch_diff.std():.2f}")
    print(f"  Pixels with error > 10: {(ch_diff > 10).sum():,} ({(ch_diff > 10).sum() / ch_diff.size * 100:.2f}%)")
    print(f"  Pixels with error > 20: {(ch_diff > 20).sum():,} ({(ch_diff > 20).sum() / ch_diff.size * 100:.2f}%)")

print("\n" + "="*60)
print("Difference images saved:")
print("  _test_difference.png (actual pixel differences)")
print("  _test_difference_amplified.png (10x amplified for visibility)")
