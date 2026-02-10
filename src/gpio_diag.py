#!/usr/bin/env python3
"""GPIO diagnostic helper.

Enumerates /dev/gpiochip* devices, prints chip info (if available via lgpio),
attempts to claim provided line numbers, and reports successes.

Usage:
    python gpio_diag.py 17 27
If no line numbers are supplied it defaults to common BCM pins: 4 17 27 22.
"""
import sys, glob

try:
    import lgpio
except ImportError as e:
    print("lgpio not installed; install with: pip install lgpio", file=sys.stderr)
    sys.exit(1)

pins = [int(p) for p in sys.argv[1:]] or [4, 17, 27, 22]
chips = sorted(glob.glob('/dev/gpiochip*'))
print(f"Found chips: {', '.join(chips) if chips else 'NONE'}")
if not chips:
    sys.exit(0)

results = []
for chip_path in chips:
    chip_num = int(chip_path.replace('/dev/gpiochip',''))
    try:
        h = lgpio.gpiochip_open(chip_num)
    except Exception as e:
        print(f"Chip {chip_num}: open failed: {e}")
        continue
    print(f"Chip {chip_num}: opened")
    for pin in pins:
        try:
            lgpio.gpio_claim_input(h, pin)
            print(f"  Claim SUCCESS line {pin} on chip {chip_num}")
            results.append((pin, chip_num))
            # release for cleanliness
            lgpio.gpiochip_close(h)
            h = lgpio.gpiochip_open(chip_num)
        except Exception as e:
            print(f"  Claim fail line {pin} on chip {chip_num}: {e}")
    lgpio.gpiochip_close(h)

print("Summary:")
for pin in pins:
    matches = [c for p,c in results if p == pin]
    if matches:
        print(f"  Pin {pin} available on chip(s): {matches}")
    else:
        print(f"  Pin {pin} not claimed on any chip (try gpiod line name mapping)")

print("Next: run 'gpioinfo' and inspect line names; mapping may differ from BCM numbering.")
