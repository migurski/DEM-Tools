from sys import stderr
from urlparse import urlparse, urljoin
from os import unlink, close, write, mkdir, chmod, makedirs
from os.path import basename, exists, isdir, join
from httplib import HTTPConnection
from subprocess import Popen, PIPE
from tempfile import mkstemp
from zipfile import ZipFile
from hashlib import md5

from .SRTM3 import sref, quads, filename, datasource as srtm3_datasource

from osgeo import gdal

def vfp_datasource(lat, lon, source_dir):
    """
    """
    fmt = 'http://viewfinderpanos-index.herokuapp.com/index.php/%s.hgt'
    url = fmt % filename(lat, lon)
    
    #
    # Create a local filepath
    #
    s, host, path, p, q, f = urlparse(url)
    
    dem_dir = md5(url).hexdigest()[:3]
    dem_dir = join(source_dir, dem_dir)
    
    dem_path = join(dem_dir, basename(path))
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
    print >> stderr, 'Retrieving', url, 'in VFP.vfp_datasource().'
    
    conn = HTTPConnection(host, 80)
    conn.request('GET', path)
    resp = conn.getresponse()
    
    if resp.status == 404:
        # we're probably outside the coverage area, use SRTM3 instead
        print >> open(dem_none, 'w'), url
        return None
    
    print >> stderr, 'Found', resp.getheader('location'), 'X-Zip-Path:', resp.getheader('x-zip-path')

    assert resp.status in range(300, 399), (resp.status, resp.read())
    
    zip_location = urljoin(url, resp.getheader('location'))
    zip_filepath = resp.getheader('x-zip-path')
    
    #
    # Get the real zip archive
    #
    print >> stderr, 'Getting', zip_location

    s, host, path, p, q, f = urlparse(zip_location)

    conn = HTTPConnection(host, 80)
    conn.request('GET', path)
    resp = conn.getresponse()
    
    assert resp.status in range(200, 299), (resp.status, resp.read())
    
    try:
        #
        # Get the DEM out of the zip file
        #
        handle, zip_path = mkstemp(prefix='vfp-', suffix='.zip')
        write(handle, resp.read())
        close(handle)
        
        zipfile = ZipFile(zip_path, 'r')
        
        #
        # Write the actual DEM
        #
        print >> stderr, 'Extracting', zip_filepath, 'to', dem_path
    
        dem_file = open(dem_path, 'w')
        dem_file.write(zipfile.read(zip_filepath))
        dem_file.close()
        
        chmod(dem_path, 0666)
    
    finally:
        unlink(zip_path)

    #
    # The file better exist locally now
    #
    return gdal.Open(dem_path, gdal.GA_ReadOnly)

def datasource(lat, lon, source_dir):
    """ Return a gdal datasource for a VFP lat, lon corner.
    
        If it doesn't already exist locally in source_dir, grab a new one.
    """
    #
    # Create a local filepath
    #
    dem_dir = md5('Viewfinder Panoramas + SRTM %s.hgt' % filename(lat, lon)).hexdigest()[:3]
    dem_dir = join(source_dir, dem_dir)
    
    dem_path = join(dem_dir, 'VFP-SRTM3-%s.hgt' % filename(lat, lon))
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
    # Combine the two datasources
    #
    vfp_ds = vfp_datasource(lat, lon, source_dir)
    srtm3_ds = srtm3_datasource(lat, lon, source_dir)
    
    if vfp_ds is None and srtm3_ds is None:
        return None
    
    if vfp_ds is None:
        return srtm3_ds
    
    if srtm3_ds is None:
        return vfp_ds
    
    vfp_path, srtm3_path = vfp_ds.GetFileList()[0], srtm3_ds.GetFileList()[0]
    
    commands = [['gdalwarp', '-ot', 'Float32', '-co', 'COMPRESS=LZW', srtm3_path, dem_path],
                ['gdalwarp', '-r', 'cubic', vfp_path, dem_path],
                ['gdalwarp', srtm3_path, dem_path]]
    
    for cmd in commands:
        cmd = Popen(cmd, stdout=PIPE, stderr=PIPE)
        cmd.wait()
        
        assert cmd.returncode == 0

    #
    # The file better exist locally now
    #
    return gdal.Open(dem_path, gdal.GA_ReadOnly)

def datasources(minlon, minlat, maxlon, maxlat, source_dir):
    """ Retrieve a list of VFP or SRTM3 datasources overlapping the tile coordinate.
    """
    lonlats = quads(minlon, minlat, maxlon, maxlat)
    sources = [datasource(lat, lon, source_dir) for (lon, lat) in lonlats]
    return [ds for ds in sources if ds]
