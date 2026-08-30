const URL_PATTERN = /(https?:\/\/[^\s<]+|www\.[^\s<]+)/gi;

function trimUrl(value: string) {
  const trailing = value.match(/[),.!?:;]+$/)?.[0] ?? '';
  return { url: value.slice(0, value.length - trailing.length), trailing };
}

function linkLabel(value: string) {
  try {
    return new URL(value.startsWith('www.') ? `https://${value}` : value).hostname.replace(/^www\./, '');
  } catch {
    return 'Open link';
  }
}

export default function LinkifiedText({ text }: { text: string }) {
  const parts = text.split(URL_PATTERN);
  return (
    <>
      {parts.map((part, index) => {
        if (!/^https?:\/\//i.test(part) && !/^www\./i.test(part)) {
          return <span key={index}>{part}</span>;
        }
        const { url, trailing } = trimUrl(part);
        const href = url.startsWith('www.') ? `https://${url}` : url;
        return (
          <span key={index}>
            <a href={href} target="_blank" rel="noopener noreferrer" className="inline-link">
              {linkLabel(url)}
            </a>
            {trailing}
          </span>
        );
      })}
    </>
  );
}
