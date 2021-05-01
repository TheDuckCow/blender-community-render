# Blender Community Render

This Blender 3d python add-on helps load and render blend files in bulk such as
from a community collaboration.

This add-on built and primarily used in Blender 2.90, but may work as far
back as blender 2.80.


## What is this add-on good for?

If you are hosting a community project, where artists submit to you their blend
files, and you need a way to standardize the output (render, library linking,
etc).

The key features of this add-on include:

- Quickly load and cycle through user-submitted blend files
- Safeguard against any unique user set ups, including blocking python
  scripts from user files from running (which would be a security concern for
  the person using this add-on and loading files on their machine).
    - After using this add-on, you may want to manually re-enable auto-run
    python scripts in user preferences, if you normally enable this.
- Standardize outputs, so that you may render submissions in a way that will
  work with the project output.
- Configure to meet project needs. This is the note for developers: this add-on
  serves as a good **starting point** for customizing for another unique
  community render project.
    - The add-on on it's own probably will never be well suited for a project
    other than the sample default use case.
    - This is because the add-on works best when making specific assumptions
    about desired inputs and similarly, the desired output.
    - Even if you are using custom development time to use this starting point
    code, you still end up time vs starting from scratch!
    - Over time, sample branches/releases may be created for different use cases
    where it has been tailored to meet specific community project needs.


## Installing

### Option 1: Install for future reuse

This add-on takes the form of a single python (`.py`) file. You can install it
under Edit > User Preferences, Add-ons > Install from file. After installing, be
sure to tick the box to enable the add-on. Save user preferences to ensure it is
automatically enabled the next time you start Blender.

### Option 2: One-time load

Instead of installing the script (which )
temporarily use the add-on without installing it, by dragging and dropping the
`blender-community-render.py` file into blender's text editor. Press the play
button (or hover over the text and press `alt p`).

## Using the add-on

Now that the add-on is enabled, you can find the community render panel under
the `Scene` tab of the Properties window. This is the tab where the icon (in
Blender 2.9) looks like an upside-down cone. This panel contains all features of
 the add-on.


### Load form responses

An assumption of this add-on is that user submissions are coming from something
like a Google Form (including a file uploader). The add-on looks for a
`form_responses.tsv` file, which is a tab-separated-value download of the raw
form responses.

See the section on preparing this tsv file. This step is really only required
if you are hoping to create in-render text of the author and their country.

While there will be warnings if the tsv file is not found, the addon still works
perfectly fine without it.


### Load blend files in Blender

Press the folder icon on the second property in the Community Render panel. It
will automatically load any and all .blend files in that folder.

Conveniently, this actually works *ok-ish* with fuse files too. So for instance
if didn't want to directly download all blend files from e.g. the Google Drive
output folder, you could use something like Drive or Desktop to mount that
folder as a network drive. That being said, things will be more stable and
generally faster if you are able to directly download the whole folder and save
to a custom folder location. In my experience using Drive for Desktop, there is
surprisingly little speed gains to marking the folder offline (assuming files
from users are generally small), copying the whole folder to another local
location will work better and be more stable.

### Preparing the form responses

Assuming the submissions are done with Google Forms, the form itself would
include fields such as (titles/order do not matter here)
- Name
- Country
- The blend file upload
- Some kind of affirmation that permission is given to use info + blend

To view submissions, you can generate a spreadsheet of responses. Create a new
spreadsheet, and then you'll likely want to create a new tab which is separate
from the form responses tab. This is because the field names

The actual fields expected in the `form_responses.tsv` file are the following
(order of columns does not matter here, extra columns are fine too):
- full_name: Directly from form, used to display as text.
- country: Directly from form, used to display as text.
- blend_filename: Not actually provided by the Google Drive form. Use either an
  app script or manually join in the name of the blend files based on the drive
  file url (which *is* provided by the form output). This is used to join an
  actual blend file on disk to this row of metadata.

Final step is to download this form_responses tab as a tsv file, which you can
do so from: file > download > Tab-separated values (.tsv, current sheet).

## Contributing

Contributions are welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

## License

GPL3; see [`LICENSE`](LICENSE) for details.

## Disclaimer

This project is not an official Google project. It is not supported by
Google and Google specifically disclaims all warranties as to its quality,
merchantability, or fitness for a particular purpose.
