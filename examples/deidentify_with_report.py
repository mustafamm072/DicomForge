from dicomforge import AnonymizationPlan, DicomDataset, Tag


dataset = DicomDataset(
    {
        Tag.PatientName: "Ada Lovelace",
        Tag.PatientID: "12345",
        Tag.StudyInstanceUID: "1.2.826.0.1.3680043.10.1",
        Tag.SeriesInstanceUID: "1.2.826.0.1.3680043.10.2",
        Tag.SOPInstanceUID: "1.2.826.0.1.3680043.10.3",
        (0x0011, 0x1001): "private value",
    }
)

plan = AnonymizationPlan.starter_profile(uid_salt="example-project")
report = plan.apply_with_report(dataset)

print(dataset.to_plain_dict())
print(report.to_dict())
