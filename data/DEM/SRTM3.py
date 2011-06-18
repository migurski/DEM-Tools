""" Starting point for DEM retrieval utilities.
"""
from sys import stderr
from math import floor, log
from os import unlink, close, write, mkdir, chmod
from os.path import basename, exists, isdir, join
from httplib import HTTPConnection
from urlparse import urlparse
from tempfile import mkstemp
from zipfile import ZipFile
from hashlib import md5

from TileStache.Geography import SphericalMercator

from osgeo import gdal, osr

source_dir = 'source'
ideal_zoom = 10 ## log(1200*360 / 256) / log(2) # ~10.7

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

sref = osr.SpatialReference()
sref.ImportFromProj4('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')

def region(lat, lon):
    """ Return the SRTM3 region name of a given lat, lon.
    
        Map of regions:
        http://dds.cr.usgs.gov/srtm/version2_1/Documentation/Continent_def.gif
    """
    if 15 <= lat and lat < 61 and -170 <= lon and lon < -40:
        return 'North_America'
    
    raise ValueError('Unknown location: %s, %s' % (lat, lon))

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

def datasource(lat, lon):
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

    fmt = 'http://dds.cr.usgs.gov/srtm/version2_1/SRTM3/%s/N%dW%d.hgt.zip'
    url = fmt % (reg, abs(lat), abs(lon))
    
    #
    # Create a local filepath
    #
    s, host, path, p, q, f = urlparse(url)
    
    dem_dir = md5(url).hexdigest()[:2]
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
        mkdir(dem_dir)
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

def datasources(minlon, minlat, maxlon, maxlat):
    """ Retrieve a list of SRTM3 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]
