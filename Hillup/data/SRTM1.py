""" Starting point for DEM retrieval utilities.
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

ideal_zoom = 13 ## log(3600*360 / 256) / log(2) # ~12.3

osr.UseExceptions() # <-- otherwise errors will be silent and useless.

sref = osr.SpatialReference()
sref.ImportFromProj4('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')

def region(lat, lon):
    """ Return the SRTM1 region number of a given lat, lon.
    
        Map of regions:
        http://dds.cr.usgs.gov/srtm/version2_1/SRTM1/Region_definition.jpg
    """
    if 38 <= lat and lat < 50 and -125 <= lon and lon < -111:
        return 1
    
    if 38 <= lat and lat < 50 and -111 <= lon and lon < -97:
        return 2
    
    if 38 <= lat and lat < 50 and -97 <= lon and lon < -83:
        return 3
    
    if 28 <= lat and lat < 38 and -123 <= lon and lon < -100:
        return 4
    
    if 25 <= lat and lat < 38 and -100 <= lon and lon < -83:
        return 5
    
    if 17 <= lat and lat < 48 and -83 <= lon and lon < -64:
        return 6
    
    if -15 <= lat and lat < 60 and ((172 <= lon and lon < 180) or (-180 <= lon and lon < -129)):
        return 7
    
    raise ValueError('Unknown location: %s, %s' % (lat, lon))

def quads(minlon, minlat, maxlon, maxlat):
    """ Generate a list of southwest (lon, lat) for 1-degree quads of SRTM1 data.
    """
    lon = floor(minlon)
    while lon <= maxlon:
    
        lat = floor(minlat)
        while lat <= maxlat:
        
            yield lon, lat
        
            lat += 1
    
        lon += 1

def datasource(lat, lon, source_dir):
    """ Return a gdal datasource for an SRTM1 lat, lon corner.
    
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

    # FIXME for western / southern hemispheres
    fmt = 'http://dds.cr.usgs.gov/srtm/version2_1/SRTM1/Region_%02d/N%02dW%03d.hgt.zip'
    url = fmt % (reg, abs(lat), abs(lon))
    
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
    print >> stderr, 'Retrieving', url, 'in DEM.SRTM1.datasource().'
    
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
        handle, zip_path = mkstemp(prefix='srtm1-', suffix='.zip')
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
    """ Retrieve a list of SRTM1 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon, source_dir) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]
