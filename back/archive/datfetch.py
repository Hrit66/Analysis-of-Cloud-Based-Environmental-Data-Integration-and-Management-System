import imdlib as imd

for var in ['rain', 'tmax', 'tmin']:
    imd.get_data(var, 2023, 2024, fn_format='yearwise', file_dir='imd_data')

for var in ['rain', 'tmax', 'tmin']:
    data = imd.open_data(var, 2023, 2024, 'yearwise', 'imd_data')
    data.to_csv(f'{var}_bengaluru.csv', 12.97, 77.59, 'imd_data')