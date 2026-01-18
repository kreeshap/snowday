import streamlit as st
from mainapp import get_snow_day_probabilities  # updated function name

st.set_page_config(page_title="Snow Day Calculator")

st.title("Snow Day Calculator")
st.write("enter yo zipcode")

zipcode = st.text_input("zip code", max_chars=5, placeholder="48167")

if st.button("calculate", type="primary"):
    if not zipcode or len(zipcode) != 5 or not zipcode.isdigit():
        st.error("for the love of god enter a real zip code")
    else:
        with st.spinner("cookin up"):
            result = get_snow_day_probabilities(zipcode)
        
        if result['success']:
            st.success(f"yo im done cookin up {result['location']}")
            
            # Loop through each day and assign color individually
            for day in result['probabilities']:
                prob = day['probability']
                if prob >= 75:
                    color = "🔴"
                elif prob >= 55:
                    color = "🟠"
                elif prob >= 35:
                    color = "🟡"
                else:
                    color = "🟢"
                
                st.markdown(f"### {color} {day['weekday']} ({day['date']})")
                st.markdown(f"**Probability:** {day['probability']}%")
                st.markdown(f"**Likelihood:** {day['likelihood']}")
            
            st.caption(f"last cooked up: {result['timestamp']}")
        else:
            st.error(f"Error: {result['error']}")
