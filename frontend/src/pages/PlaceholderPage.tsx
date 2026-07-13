type PlaceholderPageProps = {
  title: string;
  description: string;
};

export function PlaceholderPage(props: PlaceholderPageProps) {
  return (
    <section className="panel">
      <h2>{props.title}</h2>
      <p>{props.description}</p>
    </section>
  );
}

