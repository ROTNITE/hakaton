"""Native acceptance of a real Windows manifest write failure, without filling a disk."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import time

from contracts.protocol import ProtocolError
from tools.native_archive import ArchiveError,verify_archive


def drive(client,output_root,decision,*,seed=2026):
    if os.name!='nt':raise RuntimeError('OS manifest-lock injection requires Windows')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE)
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    observation=client.reset(seed=seed)['observation'];episode=observation['episode_id']
    observation=client.step(decision(observation))['observation']
    directory=(Path(output_root)/'core-runs'/episode).resolve(strict=True)
    target=directory/'manifest.json.part'
    assert target.parent==directory and not target.exists()
    handle=kernel.CreateFileW(str(target),0x40000000,0,None,1,0x80,None)
    if handle in (None,ctypes.c_void_p(-1).value):raise OSError(ctypes.get_last_error(),'Cannot lock probe manifest')
    try:
        actor=next(a for a in observation['agents'] if a['kind']=='aerial')
        x,y,_=actor['position']
        request=decision(observation,commands=[{'agent_id':actor['id'],'action':'follow_route',
            'parameters':{'waypoints':[[x,y,20.]]}}])
        errors=[]
        # Same body twice: a pre-manifest replay record must not claim success.
        for _ in range(2):
            try:client.step(request)
            except ProtocolError as error:
                assert error.code=='INTERNAL_ERROR' and 'archive manifest' in error.message
                errors.append({'code':error.code,'message':error.message})
            else:raise AssertionError('Manifest failure was acknowledged as a successful step')
        failed=client.observation()
        assert failed['mission']['status']=='failed'
        assert failed['mission']['termination']['reason']=='archive_io_failed'
    finally:kernel.CloseHandle(handle)
    time.sleep(.25)
    stopped=client.observation()
    assert failed['time']==stopped['time']
    assert [(a['id'],a['position']) for a in failed['agents']]==[(a['id'],a['position']) for a in stopped['agents']]
    try:client.step(decision(stopped))
    except ProtocolError as error:assert error.code=='INTERNAL_ERROR'
    else:raise AssertionError('Failed storage episode advanced on a new decision')
    closed=client.close(episode);assert closed['closed'] and closed['status']=='failed'
    return {'passed':True,'fixture':'native-manifest-write-failure','episode_id':episode,
            'expected_archive_statuses':{episode:'failed'},'errors':errors,
            'failed_time':failed['time'],'stopped_time':stopped['time'],
            'physical_pause_confirmed':True,'actual_disk_full_tested':False,
            'injection':'exclusive_OS_handle_on_own_manifest_part'}


def verify(result,output_root):
    directory=Path(output_root)/'core-runs'/result['episode_id']
    try:verify_archive(directory)
    except ArchiveError as error:
        assert str(error)=='Native archive is incomplete';result['reader_rejection']=str(error)
    else:raise AssertionError('Incomplete archive was accepted as complete evidence')
