// Power Query (M): loads one table from the pipeline's output folder.
// 1. In Power BI: Transform data > Manage parameters > New parameter "DataFolder"
//    (Text), value = the full path of data_powerbi\ ending with a backslash.
// 2. New blank query per table, paste this, and change the file name.
let
    Source = Csv.Document(
        File.Contents(DataFolder & "fact_transactions.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Headers, {
        {"due_date", type date}, {"accrual_date", type date}, {"payment_date", type date},
        {"amount", type number}, {"amount_paid", type number}, {"amount_open", type number}
    }, "en-US"),
    // One key per company + category, because each company has its own chart of accounts.
    CategoryKey = Table.AddColumn(Typed, "category_key", each [company] & "|" & [category_id], type text)
in
    CategoryKey
