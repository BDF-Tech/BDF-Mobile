from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in mobile/__init__.py
from mobile import __version__ as version

setup(
	name="mobile",
	version=version,
	description="Mobile",
	author="Qunatbit",
	author_email="pradip.jadhav@erpdata.in",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
