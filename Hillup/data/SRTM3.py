""" Starting point for DEM retrieval utilities.

>>> region(32, -65)
'North_America'

>>> region(40, -100)
'North_America'

>>> region(51, 17)
'Eurasia'

>>> region(20, 100)
'Eurasia'

>>> region(55, -175)
'Eurasia'

>>> region(0, -160)
'Eurasia'

>>> region(-13, 96)
'Eurasia'

>>> region(-32, 159)
'Australia'

>>> region(-20, 63)
'Africa'

>>> region(39, -32)
'Africa'

>>> region(0, 0)
'Africa'

>>> region(-30, 167)
'Islands'

>>> region(-38, 77)
'Islands'

>>> region(-8, -15)
'Islands'

>>> region(-55, -35)
'Islands'

>>> region(20, -155)
'Islands'

>>> region(-45, -180)
'Islands'
"""
from sys import stderr
from math import floor, log
from os import unlink, close, write, chmod, makedirs
from os.path import basename, exists, isdir, join
from httplib import HTTPConnection
from urlparse import urlparse
from tempfile import mkstemp
from zipfile import ZipFile
from hashlib import md5

from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr

ideal_zoom = 10 ## log(1200*360 / 256) / log(2) # ~10.7

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

sref = osr.SpatialReference()
sref.ImportFromProj4('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')

def region(lat, lon):
    """ Return the SRTM3 region name of a given lat, lon.
    
        Map of regions:
        http://dds.cr.usgs.gov/srtm/version2_1/Documentation/Continent_def.gif
    """
    if -45 <= lat and lat < -25 and -180 <= lon and lon < -175:
        # southern hemisphere, near dateline
        return 'Islands'
    
    elif 15 <= lat and lat < 30 and -180 <= lon and lon < -150:
        # around hawaii
        return 'Islands'
    
    elif -60 <= lat and lat < -35 and -40 <= lon and lon < 80:
        # south atlantic ocean
        return 'Islands'
    
    elif -35 <= lat and lat < -5 and -30 <= lon and lon < -5:
        # mid-atlantic, between africa and south america
        return 'Islands'
    
    elif -60 <= lat and lat < -40 and 155 <= lon and lon < 180:
        # southern half of new zealand
        return 'Islands'
    
    elif -40 <= lat and lat < -25 and 165 <= lon and lon < 180:
        # northern half of new zealand
        return 'Islands'
    
    if 15 <= lat and lat < 61 and -170 <= lon and lon < -40:
        return 'North_America'
    
    elif -60 <= lat and lat < 15 and -95 <= lon and lon < -30:
        return 'South_America'
    
    elif -35 <= lat and lat < 35 and -30 <= lon and lon < 60:
        return 'Africa'
    
    elif -20 <= lat and lat < -15 and 60 <= lon and lon < 65:
        return 'Africa'
    
    elif 35 <= lat and lat < 40 and -35 <= lon and lon < -20:
        return 'Africa'
    
    elif -10 <= lat and lat < 61 and -15 <= lon and lon < 180:
        return 'Eurasia'
    
    elif -10 <= lat and lat < 61 and -180 <= lon and lon < -135:
        return 'Eurasia'
    
    elif -15 <= lat and lat < -10 and 95 <= lon and lon < 100:
        return 'Eurasia'
    
    elif -45 <= lat and lat < -10 and 110 <= lon and lon < 180:
        return 'Australia'
    
    raise ValueError('Unknown location: %s, %s' % (lat, lon))

def filename(lat, lon):
    """ Return an SRTM3 filename with no extension, e.g. "N37W123".
    """
    if lat < 0 and lon < 0:
        NS, EW = 'S', 'W'
    elif lat < 0:
        NS, EW = 'S', 'E'
    elif lat >= 0 and lon < 0:
        NS, EW = 'N', 'W'
    elif lat >= 0:
        NS, EW = 'N', 'E'

    return '%s%02d%s%03d' % (NS, abs(lat), EW, abs(lon))

def quads(minlon, minlat, maxlon, maxlat):
    """ Generate a list of southwest (lon, lat) for 1-degree quads of SRTM3 data.
    """
    lon = floor(minlon)
    while lon <= maxlon:
    
        lat = floor(minlat)
        while lat <= maxlat:
        
            yield lon, lat
        
            lat += 1
    
        lon += 1

def datasource(lat, lon, source_dir):
    """ Return a gdal datasource for an SRTM3 lat, lon corner.
    
        If it doesn't already exist locally in source_dir, grab a new one.
    """
    #
    # Create a URL
    #
    try:
        reg = region(lat, lon)
    except ValueError:
        # we're probably outside a known region
        return None

    fmt = 'http://dds.cr.usgs.gov/srtm/version2_1/SRTM3/%s/%s.hgt.zip'
    url = fmt % (reg, filename(lat, lon))
    
    #
    # Create a local filepath
    #
    s, host, path, p, q, f = urlparse(url)
    
    dem_dir = md5(url).hexdigest()[:3]
    dem_dir = join(source_dir, dem_dir)
    
    dem_path = join(dem_dir, basename(path)[:-4])
    dem_none = dem_path[:-4]+'.404'
    
    #
    # Check if the file exists locally
    #
    if exists(dem_path):
        return gdal.Open(dem_path, gdal.GA_ReadOnly)

    if exists(dem_none):
        return None

    if not exists(dem_dir):
        makedirs(dem_dir)
        chmod(dem_dir, 0777)
    
    assert isdir(dem_dir)
    
    #
    # Grab a fresh remote copy
    #
    print >> stderr, 'Retrieving', url, 'in DEM.SRTM3.datasource().'
    
    conn = HTTPConnection(host, 80)
    conn.request('GET', path)
    resp = conn.getresponse()
    
    if resp.status == 404:
        # we're probably outside the coverage area
        print >> open(dem_none, 'w'), url
        return None
    
    assert resp.status == 200, (resp.status, resp.read())
    
    try:
        #
        # Get the DEM out of the zip file
        #
        handle, zip_path = mkstemp(prefix='srtm3-', suffix='.zip')
        write(handle, resp.read())
        close(handle)
        
        zipfile = ZipFile(zip_path, 'r')
        
        #
        # Write the actual DEM
        #
        dem_file = open(dem_path, 'w')
        dem_file.write(zipfile.read(zipfile.namelist()[0]))
        dem_file.close()
        
        chmod(dem_path, 0666)
    
    finally:
        unlink(zip_path)

    #
    # The file better exist locally now
    #
    return gdal.Open(dem_path, gdal.GA_ReadOnly)

def datasources(minlon, minlat, maxlon, maxlat, source_dir):
    """ Retrieve a list of SRTM3 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon, source_dir) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]

if __name__ == '__main__':

    import doctest
    doctest.testmod()