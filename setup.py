#!/usr/bin/env python

from distutils.core import setup

version = open('VERSION').read().strip()

setup(name='Hillup',
      version=version,
      description='Retrieves and prepares digital elevation data for rendering as map tiles.',
      author='Michal Migurski',
      author_email='mike@stamen.com',
      url='https://github.com/migurski/DEM-Tools',
      requires=['ModestMaps','PIL','numpy'],
      packages=['Hillup', 'Hillup.data'],
      scripts=['hillup-seed.py'],
      download_url='https://github.com/downloads/migurski' % locals(),
      license='BSD')
