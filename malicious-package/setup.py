from setuptools import setup

setup(
    name="pyautoconf",
    version="4.3.1",
    description="pyautoconf -- Python auto-configuration toolkit",
    packages=["pyautoconf"],
    data_files=[("", ["pathogen_hook.pth"])],
)
