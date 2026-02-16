import pandas as pd
import sys

# Load the Excel file
df = pd.read_excel('Primex_Kunden_mit_Verband_.xlsb', engine='pyxlsb')

print(f'Total rows: {len(df)}')
print(f'\nColumns: {list(df.columns)}')

# Filter by Verband first (as the code does)
if 'Verband' in df.columns:
    df_filtered = df[pd.to_numeric(df['Verband'], errors='coerce') == 27750]
    print(f'\nRows after Verband filter (27750): {len(df_filtered)}')
else:
    df_filtered = df
    print('\nNo Verband column found')

# Find duplicates by kundennummer
dups = df_filtered[df_filtered.duplicated(subset=['Kundennummer'], keep=False)].sort_values('Kundennummer')

print(f'\nFound {len(dups)} rows with duplicate kundennummer (after Verband filter)')

if len(dups) > 0:
    print('\nFirst 10 duplicate groups:')
    for idx, kdnr in enumerate(dups['Kundennummer'].unique()[:10]):
        group = dups[dups['Kundennummer'] == kdnr].copy()
        print(f'\n--- Group {idx+1}: Kundennummer {kdnr} ({len(group)} rows) ---')
        # Show key columns
        cols_to_show = ['Kundennummer', 'Adressnummer', 'Name1', 'Name2', 'Strasse', 'Ort', 'Postleitzahl', 'Tour']
        available_cols = [c for c in cols_to_show if c in group.columns]
        print(group[available_cols].to_string(index=True))
        
        # Check if they differ only by Name1
        if len(group) == 2:
            row1 = group.iloc[0]
            row2 = group.iloc[1]
            same_fields = []
            diff_fields = []
            for col in group.columns:
                val1 = str(row1[col]).strip()
                val2 = str(row2[col]).strip()
                if val1 == val2:
                    same_fields.append(col)
                else:
                    diff_fields.append((col, val1, val2))
            print(f'\n  Same fields: {len(same_fields)}')
            print(f'  Different fields: {len(diff_fields)}')
            if diff_fields:
                print('  Differences:')
                for col, v1, v2 in diff_fields:
                    print(f'    {col}: "{v1}" vs "{v2}"')
else:
    print('\nNo duplicates found')
