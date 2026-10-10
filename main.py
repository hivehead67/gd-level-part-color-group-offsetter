import base64
import gzip
import os
import re
import zlib

# python + one use class = welcome to programming


COLOR_MIN, COLOR_MAX = 1, 999
GROUP_MIN, GROUP_MAX = 1, 9999


COLOR_KEYS = {"21", "22", "23", "50"}

GROUP_KEYS = {"51", "71"}

GROUP_LIST_KEY = "57"

LEGACY_COLOR_TRIGGERS = {"221": 1, "717": 2, "718": 3, "743": 4}
COLOR_TRIGGER_ID = "899"

def decode_level(s):
    if s.startswith("kS"):
        return s
    raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    return zlib.decompress(raw, 15 + 32).decode("latin-1")


def encode_level(s):
    data = gzip.compress(s.encode("latin-1"), mtime=0)
    return base64.urlsafe_b64encode(data).decode("ascii")

class Shifter:
    def __init__(self, color_off, group_off):
        self.color_off = color_off
        self.group_off = group_off
        self.errors = []
        self.colors_used = set()
        self.groups_used = set()
        self.header_colors = 0   # color values changed in the header's channel list
        self.obj_colors = 0      # color values changed on objects/triggers
        self.legacy_converted = 0  # old color triggers converted to standard color triggers
        self.default_triggers_fixed = 0  # color triggers that had no target key (default channel 1)

    def _shift(self, value, offset, lo, hi, label):
        try:
            n = int(value)
        except ValueError:
            return value
        if n < lo or n > hi:        # 0 = none, >hi = special channel, leave alone
            return value
        new = n + offset
        if new < lo or new > hi:
            self.errors.append(f"{label} {n} -> {new} is out of range ({lo}-{hi})")
            return value
        if label == "Color":
            self.colors_used.add(n)
        else:
            self.groups_used.add(n)
        return str(new)

    def color(self, v):
        return self._shift(v, self.color_off, COLOR_MIN, COLOR_MAX, "Color")

    def group(self, v):
        return self._shift(v, self.group_off, GROUP_MIN, GROUP_MAX, "Group")

    def object(self, obj):
        parts = obj.split(",")
        if len(parts) % 2:
            return obj
        keys, vals = parts[0::2], parts[1::2]
        info = dict(zip(keys, vals))
        # pulse trigger: key 52 = target type 0 (or missing) = color channel, 1 = group
        pulse_color_target = info.get("1") == "1006" and info.get("52", "0") == "0"

        for i, k in enumerate(keys):
            if k in COLOR_KEYS:
                new = self.color(vals[i])
                self.obj_colors += new != vals[i]
                vals[i] = new
            elif k == "51" and pulse_color_target:
                new = self.color(vals[i])           # pulse trigger
                self.obj_colors += new != vals[i]
                vals[i] = new
            elif k in GROUP_KEYS:
                vals[i] = self.group(vals[i])
            elif k == GROUP_LIST_KEY:
                vals[i] = ".".join(self.group(g) for g in vals[i].split("."))

        # legacy color triggers
        legacy_id = info.get("1")
        if self.color_off and legacy_id in LEGACY_COLOR_TRIGGERS:
            if "23" not in keys:
                old = LEGACY_COLOR_TRIGGERS[legacy_id]
                new = self.color(str(old))
                if new != str(old):
                    keys.append("23")
                    vals.append(new)
                    self.obj_colors += 1
                    vals[keys.index("1")] = COLOR_TRIGGER_ID
                    self.legacy_converted += 1
            else:
                vals[keys.index("1")] = COLOR_TRIGGER_ID
                self.legacy_converted += 1

        # standard color trigger
        if self.color_off and legacy_id == COLOR_TRIGGER_ID and "23" not in keys:
            new = self.color("1")
            if new != "1":
                keys.append("23")
                vals.append(new)
                self.obj_colors += 1
                self.default_triggers_fixed += 1

        out = []
        for k, v in zip(keys, vals):
            out += [k, v]
        return ",".join(out)

    def header(self, header):
        parts = header.split(",")
        # find the color channel list (kS38)
        for i in range(len(parts) - 1):
            if parts[i] == "kS38":
                channels = parts[i + 1].split("|")
                parts[i + 1] = "|".join(self.channel(c) for c in channels)
        return ",".join(parts)

    def channel(self, entry):
        if not entry:
            return entry
        bits = entry.split("_")
        for j in range(0, len(bits) - 1, 2):
            if bits[j] in ("6", "9"):   # 6 = channel ID 9 = copied channel ID
                new = self.color(bits[j + 1])
                self.header_colors += new != bits[j + 1]
                bits[j + 1] = new
        return "_".join(bits)

    def level(self, text):
        sections = text.split(";")
        sections[0] = self.header(sections[0])
        for i in range(1, len(sections)):
            if sections[i]:
                sections[i] = self.object(sections[i])
        return ";".join(sections)

def ask_path():
    while True:
        p = input("path to .gmd file (you can drag and drop it here): ").strip().strip('"').strip("'")
        if os.path.isfile(p):
            return p
        print("  couldnt find file, try again")


def ask_int(prompt):
    while True:
        v = input(prompt).strip()
        if v == "":
            return 0
        try:
            return int(v)
        except ValueError:
            print("  enter a whole number (negatives are fine), or leave blank for 0")


print("=== GMD Color / Group Offsetter ===\n")
path = ask_path()

with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
    xml = f.read()

m = re.search(r"(<k>k4</k>\s*<s>)(.*?)(</s>)", xml, re.DOTALL)
if not m:
    print("couldnt find the level data in gmd file :(")
    input("\nPress Enter to exit...")
    exit()

try:
    level = decode_level(m.group(2).strip())
except Exception as e:
    print(f"couldnt decode the level data: {e}")
    input("\nPress Enter to exit...")
    exit()

print("\noffsets can be negative, leave blank for no change (why are you using this)")
print(f"regular colors are {COLOR_MIN}-{COLOR_MAX} groups are {GROUP_MIN}-{GROUP_MAX}. "
        "special channels (BG, ground, etc) are never touched.\n")

while True:
    color_off = ask_int("Color channel offset: ")
    group_off = ask_int("Group offset: ")

    shifter = Shifter(color_off, group_off)
    new_level = shifter.level(level)

    if shifter.errors:
        print("\nthat offset would push some IDs out of range:")
        for e in sorted(set(shifter.errors))[:10]:
            print("  -", e)
        print("try different offsets.\n")
        continue
    break

base, ext = os.path.splitext(path)
out_path = f"{base}_offset{ext}"
n = 2
while os.path.exists(out_path):
    out_path = f"{base}_offset{n}{ext}"
    n += 1

new_xml = xml[:m.start(2)] + encode_level(new_level) + xml[m.end(2):]
with open(out_path, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(new_xml)

print(f"\ndone! colors shifted by {color_off:+d} ({len(shifter.colors_used)} distinct channels), "
        f"groups shifted by {group_off:+d} ({len(shifter.groups_used)} distinct groups).")
print(f"  color channel list entries changed: {shifter.header_colors}")
print(f"  object/trigger color references changed: {shifter.obj_colors}")
if shifter.legacy_converted:
    print(f"  old col triggers converted to standard color triggers maybe this is prob broken im sorry but also why are you using legacy color channels: {shifter.legacy_converted}")
if color_off and not (shifter.header_colors or shifter.obj_colors):
    print("  note: no color channels were found to shift in this level.")
print(f"saved to: {out_path}")
input("\nPress Enter to exit...")
