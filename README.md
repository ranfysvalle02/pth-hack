# pth-hack

---

To build this package, you only need two files in a folder: `setup.py` (the instructions for `pip`) and `demo_hook.pth` (the file that gets executed).

### 1. The Package Configuration (`setup.py`)

This file is what `pip` reads when it installs a package. It tells `pip` what the package is called, what code it contains, and—crucially for this demo—what "extra" files to install and where to put them.

```python
# setup.py
from setuptools import setup

setup(
    name="educational-pth-demo",
    version="1.0.0",
    description="An educational demonstration of .pth file injection.",
    
    # 🚨 THE AUTOMAGIC HAPPENS HERE 🚨
    # 'data_files' allows a package to place files outside of its own folder.
    # The '' (empty string) means "put this directly into the root of site-packages".
    # This instructs pip to take 'demo_hook.pth' and put it exactly where Python 
    # looks for startup files, rather than safely inside a package folder.
    data_files=[('', ['demo_hook.pth'])],
)
```

### 2. The Payload (`demo_hook.pth`)

This is the file `pip` will drop into your environment. Because Python's startup sequence reads `.pth` files and executes any line that starts with the exact word `import`, we can put our code right on that line. 

```python
# demo_hook.pth
import sys; print("\n⚠️ [EDUCATIONAL DEMO] Your Python environment has been hooked! This ran before your script.\n", file=sys.stderr)
```
*(Note: In a real attack like the LiteLLM incident, this one-liner would import the `subprocess` module and quietly launch a hidden background script to steal files, rather than printing a visible warning).*

---

### How to Test

If you were to test this safely in a virtual environment, the workflow looks like this:

1. **You build the package:** You run a build command (like `python setup.py bdist_wheel`). This zips your two files into a `.whl` (wheel) file. This is the exact file format uploaded to PyPI.
2. **The victim installs it:** A user runs `pip install educational-pth-demo-1.0.0.whl`.
3. **Pip follows orders:** `pip` reads the `setup.py` instructions inside the wheel, extracts `demo_hook.pth`, and places it directly into the virtual environment's `site-packages` directory.
4. **The trap is set:** Now, simply typing `python -c "print('Hello World')"` in the terminal will output:

```text
⚠️ [EDUCATIONAL DEMO] Your Python environment has been hooked! This ran before your script.

Hello World
```

---

### Valid Uses vs. Potential Risks

You might wonder why Python allows packages to drop executable files into a startup directory at all. 

| Aspect | Description |
| :--- | :--- |
| **Valid, Legitimate Uses** | Legitimate tools use this to "wrap" your Python environment without you having to change your code. For example, the **`coverage.py`** tool (used to check how much of your code is tested) uses a `.pth` file to start monitoring Python's internal state the millisecond Python wakes up, before your actual application code starts running. Another common use is "editable installs" (`pip install -e .`), which use `.pth` files to link your live source code to the environment. |
| **The Security Risks** | Because `pip` blindly trusts the `setup.py` file, any package you install from PyPI has the power to place a `.pth` file in your environment. If a popular package is hijacked (like `litellm`), the attacker gains **complete persistence**. They don't have to wait for you to import their specific package; they hijack the entire Python interpreter, meaning every single script you run on that machine will execute their malware first. |

## how you can crack open a downloaded `.whl` file (like the one the LiteLLM attackers uploaded) and inspect its contents to spot a malicious `.pth` file *before* you install it?

It is actually surprisingly easy to do this once you know the secret of how Python packaging works: **a `.whl` (wheel) file is literally just a standard ZIP archive with a different file extension.**

Because it's just a ZIP file, you do not need `pip` or Python to look inside it. You can inspect its contents safely using standard tools, completely neutralizing the threat of an automagic install.

Here are two ways to crack open a wheel and hunt for malicious `.pth` files before they ever touch your system.

### Method 1: The Quick Command Line Check

If you have downloaded a wheel file (e.g., `litellm-1.82.8-py3-none-any.whl`), you can use standard command-line zip utilities to list its contents without extracting or running anything.

**On Mac/Linux:**
Use the `unzip` command with the `-l` (list) flag:
```bash
unzip -l litellm-1.82.8-py3-none-any.whl | grep "\.pth"
```
*If this command outputs anything, it means there is a `.pth` file trying to sneak into your environment.*

**On Windows:**
You can actually just rename the file from `.whl` to `.zip`, double-click it, and look around using the standard Windows File Explorer. 

### Method 2: The Python Inspection Script

If you want to automate this check for your own security tooling, you can write a short Python script using the built-in `zipfile` module. This script safely peeks inside the wheel and flags any `.pth` files.

Save this as `inspect_wheel.py`:

```python
import zipfile
import sys

def check_wheel_for_pth(wheel_path):
    print(f"[*] Inspecting: {wheel_path}")
    
    try:
        # Open the wheel file purely as a ZIP archive (safe, no execution)
        with zipfile.ZipFile(wheel_path, 'r') as wheel:
            # Get a list of all files inside the archive
            file_names = wheel.namelist()
            
            # Filter for files ending in .pth
            pth_files = [f for f in file_names if f.endswith('.pth')]
            
            if pth_files:
                print("🚨 WARNING: Found .pth file(s) in this package!")
                for pth in pth_files:
                    print(f"   -> {pth}")
                print("\n[!] Do not install this package unless you explicitly trust these .pth files.")
            else:
                print("✅ Clean: No .pth files found.")
                
    except zipfile.BadZipFile:
        print("❌ Error: Not a valid wheel/zip file.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_wheel.py <path_to_wheel_file>")
    else:
        check_wheel_for_pth(sys.argv[1])
```

**How to run it:**
```bash
python inspect_wheel.py downloaded_package.whl
```

### Where do the dangerous files hide?

When you inspect a malicious wheel like the one from the LiteLLM attack, you are looking for `.pth` files in two specific places inside the ZIP structure:

1. **The Root Directory:** If you see a file like `litellm_init.pth` sitting right at the base level of the ZIP archive (not inside a folder), that means `pip` will drop it directly into the root of your `site-packages` directory. This is the prime execution zone for this attack.
2. **The `.data` Directory:** Wheel files sometimes have a folder named `<package_name>-<version>.data/`. Inside there, a `data/` subfolder maps directly to your Python environment's root. Attackers can hide `.pth` files in here to achieve the exact same injection.

By catching these files *before* you run `pip install`, you stop the supply chain attack dead in its tracks. 
