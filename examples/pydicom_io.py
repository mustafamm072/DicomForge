from dicomforge.io import read, write


dataset = read("input.dcm", stop_before_pixels=True)
dataset.set("PatientName", "Anonymous")
write("output.dcm", dataset)
