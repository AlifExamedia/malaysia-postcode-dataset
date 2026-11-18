# malaysia-postcode-dataset

A list of Malaysian postcodes, grouped by state and city, in JSON format.

## Data source

The data comes from the **Postcode Dataset** on the Malaysian government's open data portal:

- Website: https://data.gov.my/data-catalogue/poskod
- Owner: Malaysian Communications and Multimedia Commission (MCMC)
- Licence: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

**Last updated:** 18 November 2026

This is the date the data was last taken from the source. The source may add or change postcodes after this date. If it does, we will update the data here and change this date.

## Files

Each state has its own file in `data/states/`, for example `data/states/johor.json`.

Each file looks like this:

```json
{
  "state": "Johor",
  "cities": [
    { "city": "Ayer Hitam", "postcodes": ["86100", "86107"] }
  ]
}
```

## Licence

The postcode data belongs to MCMC and is shared under the CC BY 4.0 licence. If you use it, please give credit to MCMC and data.gov.my.

The other files in this repository are under the MIT License. See [LICENSE](LICENSE).
