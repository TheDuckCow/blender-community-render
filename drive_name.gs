/* Populate uploaded filenames from a form given the entry URL

We need to correlate the row of an entry submission via google form to
the given file that was uploaded. The form response itself only
has the link to the file itself as a column value, not the filename itself.
Connecting the filename to the form row data is necessary for other processes
in the community render system.
*/

const _SHEET_NAME = 'tsv_sheet_download'; // Name of the tab to download
const _BATCH_SIZE = 100  // Number of rows to process at once.


function populateAllRows(){
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var targetSheet = ss.getSheetByName(_SHEET_NAME);
  Logger.log(targetSheet)
  var lastRow = targetSheet.getLastRow();
  Logger.log("Last row:" + lastRow.toString());

  var updated = 0
  for (var i = 1; i <= Math.floor(lastRow/_BATCH_SIZE); i++) {
    var startRow = (i - 1) * _BATCH_SIZE + 1
    var endRow = startRow + _BATCH_SIZE - 1
    if (endRow > lastRow){
      endRow = lastRow
    }
    updated = updated + populateRow(targetSheet, startRow, endRow);
  }
  Logger.log("Done, updated " + updated.toString())
}

function populateRow(sheet, startRow, endRow) {
  const readCol = 5; // E
  const writeCol = 6; // F
  Logger.log(startRow.toString() +", " + endRow.toString())

  var readUrls = sheet.getRange(startRow, readCol, endRow-startRow+1, 1).getValues()
  var writeRange = sheet.getRange(startRow, writeCol, endRow-startRow+1, 1)
  var writeNames = writeRange.getValues()
  var updated = 0;

  for (var i = 0; i <= endRow-startRow; i++) {
    if (writeNames[i] != ""){
      continue // data already loaded
    }
    // Logger.log('No data for index, load row '+(startRow+i).toString());
    // all have prefix: https://drive.google.com/open?id=
    var id = readUrls[i][0].substring(33, readUrls[i][0].length);
    // Logger.log(id)
    var this_file = ""
    try {
      var this_file = DriveApp.getFileById(id)
    }
    catch(err) {
      Logger.log("Failed to pull id "+id.toString()+" from row "+(startRow+i).toString())
      writeNames[i] = ['']
      continue
    }
    writeNames[i] = [this_file.getName()]
    updated = updated + 1;
  }
  // Logger.log("Writing names:");
  // Logger.log(writeNames);
  writeRange.setValues(writeNames);
  return updated;
}
