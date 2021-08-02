:: License: GPL v3
@echo off

:: Assign the explicit version of blender to use, full path
set blender="C:\path\blender\blender.exe"

:: Full path to where the source blend files are saved
set src_files="D:\blender\file\submissions"

:: Specify the source blend to open as the render template
set render_template="G:\working_directory\render_template.blend"

:: Specify the addon itself, should be the SAME directory as this script runs from
set addon_py="G:\working_directory\community_render.py"

:: Only need to make modifications above!

:: Create the file for indicating renders are in progress
set restarter="restart_until_finished.txt"
break>%restarter%

if not exist %blender% (
    echo "Blender file is missing, exiting"
    goto :eof
)

if not exist %src_files% (
    echo "Source files missing, exiting"
    goto :eof
)

if not exist %render_template% (
    echo "Render template missing missing, exiting"
    goto :eof
)

if not exist %addon_py% (
    echo "addon_py file missing missing, exiting"
    echo %addon_py%
    goto :eof
)

if not exist %restarter% (
	echo "Restarter file doesn't exist, won't ever close"
	echo %restarter%
    goto :eof
)

:: Change directory to another drive using cd /d "G:\etc"
:startloop
%blender% -b %render_template% -P startup.py -- -src_files %src_files% -addon_py %addon_py%
echo "Blender exited"

if not exist %restarter% (
	echo "Restarter file doesn't exist, render completed!"
    goto :eof
)

goto startloop
@echo on
