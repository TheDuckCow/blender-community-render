# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# Blender Community Render - OSX Guardian Wrapper
#
# Script used to auto-restart blender in case it crashes in the middle of an
# execution.

# Hard code this to match your local blender executable location.
blender='/Applications/Blender 2.93/blender.app/Contents/MacOS/blender'

# Path to where the source blend files are saved
src_files='/source/blender/files_folder'

# Specify the source blend file to open as the render template
render_template='/path/to/render_tempalte.blend'

# Assumed the source addon script is in the same directory as active directory.
# Using relative path
addon_py="community_render.py"

# Only need to make modifications above!

if [[ ! -f $blender ]] ; then
    echo "Blender file missing: $blender".
    exit
fi

# Auto restart blender until THIS script is closed.
echo "Starting blender, will restart until this process is closed."

restarter="restart_until_finished.txt"
touch $restarter

while true
do
	echo "> Starting blender in 3s (ctrl c to cancel or close window)..."
	sleep 3
	"$blender" -b "$render_template" -P startup.py -- \
		-src_files "$src_files" \
		-addon_py "$(pwd)/$addon_py"
	echo "Blender exited"
	# exit

	if [[ ! -f $restarter ]] ; then
	    echo "Restarter file is missing, assumign render completed.".
	    exit
	fi

done
